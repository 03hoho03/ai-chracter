"""소설과 그 아래 행을 지우는 단 한 곳.

소설 단독 삭제와 회원 탈퇴가 이 함수를 같이 쓴다. 두 경로가 자식 목록을 따로 가지면 테이블이 늘 때 한쪽에만
더해지기 쉽고, 빠진 쪽은 소설 DELETE 가 FK 위반으로 500 이 된다. `ON DELETE CASCADE` 가 없으므로 자식부터 지운다.

이 모듈은 라우터를 import 하지 않는다 — `auth/withdrawal.py` 가 import 해도 순환이 생기지 않게."""

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
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
