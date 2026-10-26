"""소설의 집필권 잠금. 남의 작품으로 쓰는 소설은 첫 화가 저장된 순간 권리가 생긴다 — 그 뒤로는 작가가 소설화 허락을
낮춰도 이어 쓴다. 잠기기 전(빈 소설)은 아무 권리도 선점하지 않아 지금 허락을 따른다. 잠금은 풀리지 않고, 화를 다
지워도 남는다.

잠금은 한 번만 찍는다 — 쓰는 문장마다 `writing_locked_at IS NULL` 조건을 걸어, 먼저 찍힌 시각·출처·허락 사본·버전을
덮지 않는다."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.auth import User
from api.db.models.content import Content
from api.db.models.novel import Novel, NovelJob
from api.novelize.job_variants import kinds_where


def refuses_novelize(content: Content, user_id: uuid.UUID) -> bool:
    """작가가 소설화를 허용하지 않았고 `user_id` 가 그 작가가 아니다. 허락은 남에게 거는 조건이라 작가 본인은 늘
    통과한다."""
    return content.novel_permission == "forbidden" and content.creator_user_id != user_id


async def novelize_refused(db: AsyncSession, content: Content, user_id: uuid.UUID) -> bool:
    """`user_id` 가 이 작품으로 아직 권리를 얻지 않은 소설화(새 소설 만들기, 잠기기 전 소설의 생성)를 할 수 없는가 — 작가가
    허용하지 않았거나(`refuses_novelize`), 정책 스위치가 켜졌고 작가가 탈퇴했다. 탈퇴한 작가의 작품으로 새 소설화를 시작하지
    않게 하려는 것이고, 첫 화를 저장해 잠긴 소설은 이 판정을 지나지 않는다(이미 얻은 권리). 새 소설 만들기·방 응답의 차단
    표시·잠기기 전 소설의 생성 경로가 같은 판정을 쓴다. 작가 탈퇴는 허락이 막지 않을 때만 조회한다."""
    return content.id in await novelize_refused_contents(db, [content], user_id)


async def novelize_refused_contents(
    db: AsyncSession, contents: Sequence[Content], user_id: uuid.UUID
) -> set[uuid.UUID]:
    """`novelize_refused` 를 작품 여럿에 한 번에 판정해 막힌 작품 id 를 돌려준다. 작가 탈퇴는 허락이 막지 않는 남의 작품의
    작가만 한 번에 조회한다."""
    refused = {content.id for content in contents if refuses_novelize(content, user_id)}
    if not settings.novel_public_policy_v2_enabled:
        return refused
    others = [content for content in contents if content.id not in refused and content.creator_user_id != user_id]
    if not others:
        return refused
    withdrawn = set(
        await db.scalars(
            select(User.id).where(
                User.id.in_({content.creator_user_id for content in others}), User.deleted_at.is_not(None)
            )
        )
    )
    return refused | {content.id for content in others if content.creator_user_id in withdrawn}


async def novel_creation_blocked_rooms(
    db: AsyncSession, user_id: uuid.UUID, rooms: Sequence[tuple[uuid.UUID, Content]]
) -> set[uuid.UUID]:
    """`user_id` 의 방들(방 id, 그 원작) 중 새 소설을 만들 수 없다고 보일 방의 id. 채팅방 단건 응답과 소설로 만들 수 있는 내
    채팅 목록이 같은 판정을 쓴다.

    새 소설화가 막힌 작품(`novelize_refused`)의 방에서만 소설을 본다(방 하나에 소설 하나 — 방 유니크 인덱스로 찾는다). 잠기기
    전의 빈 소설은 이어 쓸 수 없으니 소설이 없는 것과 같이 막힌 것으로 보인다. 잠긴 소설은 화를 다 지워도 잠겨 있다. 잠금이
    없어도 성공한 화 생성 작업이 있으면 막지 않는다 — 생성 경로와 같은 판정이다. 배포가 겹치는 동안 옛 코드가 잠금 없이 첫
    화를 저장한 소설은 생성 경로를 지나야 그 자리에서 잠기는데, 여기서 막힘으로 보이면 사용자가 그 경로에 닿지 못한다. 읽기만
    하고 잠그지 않는다."""
    refused = await novelize_refused_contents(db, [content for _, content in rooms], user_id)
    refused_rooms = [room_id for room_id, content in rooms if content.id in refused]
    if not refused_rooms:
        return set()
    novels = {
        row.chat_room_id: row
        for row in (
            await db.execute(
                select(Novel.id, Novel.chat_room_id, Novel.writing_locked_at).where(
                    Novel.chat_room_id.in_(refused_rooms)
                )
            )
        ).all()
    }
    unlocked = [row.id for row in novels.values() if row.writing_locked_at is None]
    saved = await first_saved_chapter_ats(db, unlocked) if unlocked else {}
    blocked: set[uuid.UUID] = set()
    for room_id in refused_rooms:
        novel = novels.get(room_id)
        if novel is None or (novel.writing_locked_at is None and novel.id not in saved):
            blocked.add(room_id)
    return blocked


async def lock_with_first_chapter(db: AsyncSession, novel_id: uuid.UUID, content_version_id: uuid.UUID | None) -> None:
    """화 저장 트랜잭션 안에서 아직 잠기지 않은 소설을 잠근다. 허락 사본은 저장 순간의 원작 허락이다 — 요청 때 통과한
    뒤 작가가 허락을 바꿨어도 값을 치른 작업은 끝내고, 그때 실제 상태를 그대로 적는다. 원작 행이 그사이 지워졌으면
    사본은 NULL 이다(출처가 첫 화라 백필의 "알 수 없음"과는 갈린다). 원작 버전은 생성 입력이 작품 설정을 읽은 버전이다."""
    await db.execute(
        update(Novel)
        .where(Novel.id == novel_id, Novel.writing_locked_at.is_(None))
        .values(
            writing_locked_at=func.now(),
            writing_lock_permission=select(Content.novel_permission)
            .where(Content.id == Novel.content_id)
            .scalar_subquery(),
            writing_lock_content_version_id=content_version_id,
            writing_lock_source="first_chapter",
        )
    )


async def first_saved_chapter_at(db: AsyncSession, novel_id: uuid.UUID) -> datetime | None:
    """성공한 화 생성 작업(옛 흐름의 화 생성과 구성 흐름 원고) 중 가장 이른 끝난 시각 — 그 소설에 첫 화가 한 번이라도
    저장됐다는 기록이다(작업은 화 저장과 같은 트랜잭션에서만 성공이 되고, 화를 지워도 작업 행은 남는다). 연쇄 부모와 구성안
    작업은 화를 저장하지 않아 세지 않는다. 없으면 None."""
    return (await first_saved_chapter_ats(db, [novel_id])).get(novel_id)


async def first_saved_chapter_ats(db: AsyncSession, novel_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    """`first_saved_chapter_at` 을 소설 여럿에 한 번에. 첫 화가 저장된 적 없는 소설은 빠진다."""
    rows = await db.execute(
        select(NovelJob.novel_id, func.min(NovelJob.finished_at))
        .where(
            NovelJob.novel_id.in_(novel_ids),
            NovelJob.kind.in_(kinds_where(locks_writing=True)),
            NovelJob.status == "succeeded",
            NovelJob.finished_at.is_not(None),
        )
        .group_by(NovelJob.novel_id)
    )
    return {novel_id: first_at for novel_id, first_at in rows.tuples() if first_at is not None}


async def lock_as_backfill(db: AsyncSession, novel_id: uuid.UUID, locked_at: datetime) -> None:
    """잠금 없이 첫 화가 저장된 소설을 뒤늦게 잠근다. 그때의 허락·버전은 알 수 없어 비워 두고 출처로 그 사실을 남긴다."""
    await db.execute(
        update(Novel)
        .where(Novel.id == novel_id, Novel.writing_locked_at.is_(None))
        .values(writing_locked_at=locked_at, writing_lock_source="backfill")
    )
