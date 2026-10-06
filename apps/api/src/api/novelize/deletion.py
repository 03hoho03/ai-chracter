"""소설과 그 아래 행을 지우는 단 한 곳, 그리고 더 쓸 데가 없어진 AI 수정 지시문·결과 본문을 비우는 곳.

소설 단독 삭제와 회원 탈퇴가 이 함수를 같이 쓴다. 두 경로가 자식 목록을 따로 가지면 테이블이 늘 때 한쪽에만
더해지기 쉽고, 빠진 쪽은 소설 DELETE 가 FK 위반으로 500 이 된다. `ON DELETE CASCADE` 가 없으므로 자식부터 지운다.

이 모듈은 라우터를 import 하지 않는다 — `auth/withdrawal.py` 가 import 해도 순환이 생기지 않게."""

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel import Novel, NovelChapter, NovelChapterRevision, NovelJob


async def delete_novels(db: AsyncSession, novel_ids: Sequence[uuid.UUID]) -> None:
    """`novel_ids` 소설들을 작업 → 장 개정 → 장 → 소설 순으로 지운다. 커밋은 호출부가 한다.

    작업 행이 맨 앞인 이유는 둘이다. 작업이 장·개정을 FK 로 가리키므로 먼저 지워야 하고, 진행 중 작업이 성공을
    저장하는 트랜잭션과 겹쳤을 때도 안전해진다 — 성공 쪽이 작업 행을 잡고 있으면 이 DELETE 가 기다렸다가 뒤 문장들이
    새로 커밋된 장까지 보고 지우고, 이쪽이 먼저 지웠으면 성공 쪽의 조건부 상태 전이가 0행이 되어 장을 넣지 않는다.
    진행 중 작업의 환불은 이 함수가 하지 않는다 — 소설 단독 삭제는 부르기 전에 환불하고, 탈퇴는 잔액을 통째로
    소멸시키므로 환불하지 않는다.

    각 DELETE 는 `db.execute` 로 그 자리에서 실행되는 SQL 문이라 적은 순서대로 나간다. ORM 객체를 `db.delete()` 로
    모아 한 번에 flush 할 때처럼 SQLAlchemy 가 순서를 바꾸지 않으므로 단계 사이 `flush()` 는 필요 없다. 되돌리기
    개정이 같은 테이블의 앞 개정을 가리키지만 한 문장 안에서 함께 지우므로 FK 위반이 나지 않는다."""
    if not novel_ids:
        return
    chapter_ids = select(NovelChapter.id).where(NovelChapter.novel_id.in_(novel_ids))
    await db.execute(delete(NovelJob).where(NovelJob.novel_id.in_(novel_ids)))
    # 직접 수정·되돌리기·AI 수정 적용은 장 행을 잠근 채 새 개정을 넣는다. 장을 먼저 잠가 그 저장이 끝나기를 기다린다
    # — 잠그지 않으면 아래 개정 DELETE 가 아직 커밋되지 않은 새 개정을 못 보고 지나가고, 장 DELETE 가 그 개정의 FK
    # 에 걸린다. 기다린 뒤의 개정 DELETE 는 새 문장이라 커밋된 새 개정까지 본다.
    await db.execute(select(NovelChapter.id).where(NovelChapter.novel_id.in_(novel_ids)).with_for_update())
    await db.execute(delete(NovelChapterRevision).where(NovelChapterRevision.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelChapter).where(NovelChapter.novel_id.in_(novel_ids)))
    await db.execute(delete(Novel).where(Novel.id.in_(novel_ids)))


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
