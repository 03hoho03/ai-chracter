"""소설의 집필권 잠금. 남의 작품으로 쓰는 소설은 첫 화가 저장된 순간 권리가 생긴다 — 그 뒤로는 작가가 소설화 허락을
낮춰도 이어 쓴다. 잠기기 전(빈 소설)은 아무 권리도 선점하지 않아 지금 허락을 따른다. 잠금은 풀리지 않고, 화를 다
지워도 남는다.

잠금은 한 번만 찍는다 — 쓰는 문장마다 `writing_locked_at IS NULL` 조건을 걸어, 먼저 찍힌 시각·출처·허락 사본·버전을
덮지 않는다."""

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.content import Content
from api.db.models.novel import Novel, NovelJob


def refuses_novelize(content: Content, user_id: uuid.UUID) -> bool:
    """작가가 소설화를 허용하지 않았고 `user_id` 가 그 작가가 아니다. 허락은 남에게 거는 조건이라 작가 본인은 늘
    통과한다. 새 소설 만들기·방 응답의 차단 표시·잠기기 전 소설의 생성 경로가 같은 판정을 쓴다."""
    return content.novel_permission == "forbidden" and content.creator_user_id != user_id


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
    """성공한 화 생성 작업 중 가장 이른 끝난 시각 — 그 소설에 첫 화가 한 번이라도 저장됐다는 기록이다(작업은 화 저장과
    같은 트랜잭션에서만 성공이 되고, 화를 지워도 작업 행은 남는다). 연쇄 부모는 화를 저장하지 않아 세지 않는다. 없으면
    None."""
    first_at: datetime | None = await db.scalar(
        select(func.min(NovelJob.finished_at)).where(
            NovelJob.novel_id == novel_id,
            NovelJob.kind == "chapter_generate",
            NovelJob.status == "succeeded",
            NovelJob.finished_at.is_not(None),
        )
    )
    return first_at


async def lock_as_backfill(db: AsyncSession, novel_id: uuid.UUID, locked_at: datetime) -> None:
    """잠금 없이 첫 화가 저장된 소설을 뒤늦게 잠근다. 그때의 허락·버전은 알 수 없어 비워 두고 출처로 그 사실을 남긴다."""
    await db.execute(
        update(Novel)
        .where(Novel.id == novel_id, Novel.writing_locked_at.is_(None))
        .values(writing_locked_at=locked_at, writing_lock_source="backfill")
    )
