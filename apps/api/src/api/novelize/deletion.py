"""소설과 그 아래 행을 지우는 단 한 곳, 마지막 묶음을 지우는 곳, 그리고 더 쓸 데가 없어진 AI 수정 지시문·결과 본문을
비우는 곳.

소설 단독 삭제와 회원 탈퇴가 `delete_novels` 를 같이 쓴다. 두 경로가 자식 목록을 따로 가지면 테이블이 늘 때 한쪽에만
더해지기 쉽고, 빠진 쪽은 소설 DELETE 가 FK 위반으로 500 이 된다. 뼈대 테이블(작업·개정·화·소설)에는 `ON DELETE
CASCADE` 가 없어 자식부터 지운다. 묶음·인물·등장 인물·스냅샷·읽은 위치와 노벨 공개 상태·화 공개본·텍스트 심사 기록은
부모를 지우면 함께 지워지는 cascade 지만(옛 판 코드로 되돌렸을 때 그 코드가 이 테이블들을 몰라도 지워지게 한 것이다), 여기서는
cascade 에 기대지 않고 순서를 직접 적어 잠금·삭제 순서를 고정한다.

이 모듈은 라우터를 import 하지 않는다 — `auth/withdrawal.py` 가 import 해도 순환이 생기지 않게."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel import (
    Novel,
    NovelBatch,
    NovelChapter,
    NovelChapterCharacter,
    NovelChapterRevision,
    NovelChapterPublication,
    NovelCharacter,
    NovelJob,
    NovelPublication,
    NovelReadingPosition,
    NovelScreening,
    NovelSnapshot,
)


async def delete_novels(db: AsyncSession, novel_ids: Sequence[uuid.UUID]) -> None:
    """`novel_ids` 소설들을 작업 → 화 잠금 → 읽은 위치 → 스냅샷 → 등장 인물 → 인물 → 텍스트 심사 기록 → 화 공개본 → 개정 →
    화 → 묶음 → 공개 상태 → 소설 순으로 지운다. 커밋은 호출부가 한다. 화 공개본은 개정을 가리키므로 개정보다 먼저다.

    작업 행이 맨 앞인 이유는 둘이다. 작업이 화·개정을 FK 로 가리키므로 먼저 지워야 하고, 진행 중 작업이 성공을
    저장하는 트랜잭션과 겹쳤을 때도 안전해진다 — 성공 쪽이 작업 행을 잡고 있으면 이 DELETE 가 기다렸다가 뒤 문장들이
    새로 커밋된 화까지 보고 지우고, 이쪽이 먼저 지웠으면 성공 쪽의 조건부 상태 전이가 0행이 되어 화를 넣지 않는다.
    진행 중 작업의 환불은 이 함수가 하지 않는다 — 소설 단독 삭제는 부르기 전에 환불하고, 탈퇴는 잔액을 통째로
    소멸시키므로 환불하지 않는다.

    화를 지우기 전에 먼저 잠근다. 직접 수정·되돌리기·AI 수정 적용은 화 행을 잠근 채 새 개정을 넣는데, 잠그지 않으면
    아래 개정 DELETE 가 아직 커밋되지 않은 새 개정을 못 보고 지나가고 화 DELETE 가 그 개정의 FK 에 걸린다. 기다린 뒤의
    개정 DELETE 는 새 문장이라 커밋된 새 개정까지 본다. 읽은 위치를 화 잠금 뒤에 지우는 것도 같은 이유다 — 위치 저장은
    화가 있는지 확인하며 화 행에 키 공유 잠금을 거므로, 화를 먼저 쥐면 그 저장이 끝나기를 기다렸다가 함께 지운다.

    각 DELETE 는 `db.execute` 로 그 자리에서 실행되는 SQL 문이라 적은 순서대로 나간다. ORM 객체를 `db.delete()` 로
    모아 한 번에 flush 할 때처럼 SQLAlchemy 가 순서를 바꾸지 않으므로 단계 사이 `flush()` 는 필요 없다. 되돌리기
    개정이 같은 테이블의 앞 개정을 가리키지만 한 문장 안에서 함께 지우므로 FK 위반이 나지 않는다."""
    if not novel_ids:
        return
    chapter_ids = select(NovelChapter.id).where(NovelChapter.novel_id.in_(novel_ids))
    await db.execute(delete(NovelJob).where(NovelJob.novel_id.in_(novel_ids)))
    await db.execute(select(NovelChapter.id).where(NovelChapter.novel_id.in_(novel_ids)).with_for_update())
    await db.execute(delete(NovelReadingPosition).where(NovelReadingPosition.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelSnapshot).where(NovelSnapshot.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelChapterCharacter).where(NovelChapterCharacter.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelCharacter).where(NovelCharacter.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelScreening).where(NovelScreening.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelChapterPublication).where(NovelChapterPublication.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelChapterRevision).where(NovelChapterRevision.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelChapter).where(NovelChapter.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelBatch).where(NovelBatch.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelPublication).where(NovelPublication.novel_id.in_(novel_ids)))
    await db.execute(delete(Novel).where(Novel.id.in_(novel_ids)))


async def delete_batch(db: AsyncSession, *, novel_id: uuid.UUID, batch_id: uuid.UUID) -> None:
    """묶음 하나와 그 화들을 지운다. 진행 중 작업 확인·"마지막 묶음" 판정·사용자 잠금은 호출자가 먼저 한다(커밋도).

    작업 행은 지우지 않고 그 화들을 가리키는 칸(화·기준 개정·결과 개정)과 AI 수정 지시문·결과 본문만 비운다 — 같은
    시작 메시지의 하루 재시도 상한이 작업 행 수로 세므로, 지우면 묶음을 지웠다 다시 만드는 것으로 상한이 풀린다. 차감
    기록의 작업 쪽 짝도 남는다. 작업의 개정 참조는 모두 그 작업이 가리키는 화의 개정이라, 화로 골라 셋을 함께 비운다.

    그다음 화를 잠그고(`delete_novels` 와 같은 이유) 읽은 위치·등장 인물·텍스트 심사 기록·화 공개본·개정·화·묶음 순으로
    지운다. 인물 카드는 남긴다 — 사용자가 메모를 적은 카드일 수 있고, 다른 화에도 나온다. 소설의 공개 상태 행도 남긴다 —
    지우는 것은 마지막 묶음뿐이라 남은 공개 화는 여전히 1화부터 이어지고, 공개한 화가 모두 지워져도 소설 제목·소개 사본과
    운영자 조치는 소설에 남아야 한다(다시 화를 공개하면 같은 행을 쓴다).

    잠금 순서는 작업 행 → 화 행이다(`delete_novels` 와 같다). 화 id 는 잠금 없이 고른다 — 호출자가 사용자 행을 쥐고 있어
    같은 묶음에 화를 더하거나 빼는 경로(묶음 저장·삭제)가 끼어들 수 없다. 화를 먼저 잠그고 작업 행을 고치면, 작업 행을 쥔
    채 화를 기다리는 AI 수정 적용과 서로를 기다려 한쪽이 교착 오류로 끊긴다.

    스냅샷은 남기되 지운 화의 항목을 `{chapterId, deleted: true}` 로 줄인다. 화 제목·요약·작가의 말은 지운 화의
    내용이라 지울 때 함께 사라져야 하고(처리방침의 "즉시 삭제"), 항목 자리를 남기는 것은 그 스냅샷을 복원할 때 화가
    지워졌다는 사실을 알리기 위해서다."""
    chapter_ids = list((await db.scalars(select(NovelChapter.id).where(NovelChapter.batch_id == batch_id))).all())
    await db.execute(
        update(NovelJob)
        .where(NovelJob.chapter_id.in_(chapter_ids))
        .values(chapter_id=None, base_revision_id=None, result_revision_id=None, instruction=None, result_text=None)
    )
    await db.execute(select(NovelChapter.id).where(NovelChapter.id.in_(chapter_ids)).with_for_update())
    await db.execute(delete(NovelReadingPosition).where(NovelReadingPosition.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelChapterCharacter).where(NovelChapterCharacter.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelScreening).where(NovelScreening.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelChapterPublication).where(NovelChapterPublication.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelChapterRevision).where(NovelChapterRevision.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelChapter).where(NovelChapter.id.in_(chapter_ids)))
    await _shrink_snapshot_entries(db, novel_id, {str(chapter_id) for chapter_id in chapter_ids})
    await db.execute(delete(NovelBatch).where(NovelBatch.id == batch_id))


async def _shrink_snapshot_entries(db: AsyncSession, novel_id: uuid.UUID, removed: set[str]) -> None:
    """소설의 스냅샷마다 `removed` 화의 항목을 `{chapterId, deleted: true}` 로 바꿔 쓴다. 그런 항목이 없는 스냅샷은
    건드리지 않는다."""
    snapshots = (
        await db.execute(
            select(NovelSnapshot.id, NovelSnapshot.payload).where(NovelSnapshot.novel_id == novel_id).with_for_update()
        )
    ).all()
    for snapshot_id, payload in snapshots:
        entries: list[dict[str, Any]] = payload.get("chapters", [])
        if not any(entry.get("chapterId") in removed for entry in entries):
            continue
        shrunk = [
            {"chapterId": entry["chapterId"], "deleted": True} if entry.get("chapterId") in removed else entry
            for entry in entries
        ]
        await db.execute(
            update(NovelSnapshot).where(NovelSnapshot.id == snapshot_id).values(payload={**payload, "chapters": shrunk})
        )


async def erase_stale_ai_edit_previews(db: AsyncSession, chapter_id: uuid.UUID) -> None:
    """장 `chapter_id` 의 현재 개정이 아닌 개정을 기준으로 한, 적용도 버리기도 안 한 AI 수정 결과의 지시문과 결과
    본문을 비운다. 커밋은 호출부가 한다.

    그런 결과는 적용하면 409 이고 상세의 미적용 목록에도 나오지 않아, 사용자가 버리기를 누를 길이 없다 — 비우지
    않으면 소설을 지울 때까지 아무도 볼 수 없는 사본으로 남는다. 작업 행은 남긴다(하루 재시도 상한을 행 수로 센다).

    새 개정을 커밋한 **뒤 별도 트랜잭션에서** 부른다. 개정을 쌓는 경로는 장 행을 잠그고, 적용은 작업 행 → 장 행 순서로
    잠근다 — 장을 쥔 채 작업 행을 고치면 같은 장의 적용과 서로를 기다린다. 따로 돌면 작업 행 잠금만 쥐고, 지금 커밋된
    현재 개정으로 판정하므로 몇 번 돌아도 같다. AI 수정 결과 저장은 이 함수를 부르지 않는다 — 저장할 때 장 행을
    잠그고 기준 개정이 현재인지 확인해, 낡은 결과는 아예 성공으로 남기지 않는다."""
    current = (
        select(NovelChapterRevision.id)
        .where(NovelChapterRevision.chapter_id == chapter_id)
        .order_by(NovelChapterRevision.revision_no.desc())
        .limit(1)
        .scalar_subquery()
    )
    await db.execute(
        update(NovelJob)
        .where(
            NovelJob.chapter_id == chapter_id,
            NovelJob.kind == "ai_edit",
            NovelJob.status == "succeeded",
            NovelJob.result_revision_id.is_(None),
            NovelJob.dismissed_at.is_(None),
            NovelJob.result_text.is_not(None),
            NovelJob.base_revision_id.is_distinct_from(current),
        )
        .values(instruction=None, result_text=None)
    )
