"""묶음 없는 화를 묶음에 넣는 보정 — 묶음 구조 마이그레이션의 이관과 같은 일을 소설 하나에 대해 한다.

옛 판 이미지로 되돌린 동안에는 옛 코드가 묶음 칸을 모른 채 화를 넣고(묶음 없는 화), 마지막 장 삭제로 화가 하나도 없는
묶음을 남긴다. 새 판을 다시 올려도 마이그레이션은 이미 지나 있어 그 화들은 묶음 없이 남는다. 그래서 묶음을 읽거나 새로
만드는 경로(상세·작업 생성·묶음 삭제)가 먼저 이 보정을 부른다 — 묶음 없는 화가 있으면 다시 만들기가 묶음을 찾지 못하고,
그 상태로 다음 묶음을 만들면 옛 화가 나중에 받을 묶음 번호가 화 순서와 어긋난다.

뜻은 마이그레이션의 이관 함수와 같아야 한다(테스트가 두 결과를 대조한다): 화가 하나도 없는 묶음을 지운 뒤, 묶음 없는 화마다
화 하나짜리 묶음을 만들어 그 화의 구간을 복사하고(화 수 목표 1) 묶음 번호는 그 소설의 기존 묶음 번호 뒤로 화 번호 순서대로
매긴다. 이 모듈은 마이그레이션을 import 하지 않는다 — 마이그레이션 파일은 앱 코드와 따로 돌고, 앱 코드가 리비전 파일에
기대면 리비전을 고칠 때 앱이 함께 바뀐다."""

import uuid

from sqlalchemy import exists, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel import Novel, NovelBatch, NovelChapter
from api.novelize.billing import _lock_user

_DROP_EMPTY_BATCHES_SQL = text(
    "DELETE FROM novel_batches b WHERE b.novel_id = :novel_id"
    " AND NOT EXISTS (SELECT 1 FROM novel_chapters c WHERE c.batch_id = b.id)"
)

# 마이그레이션의 이관 문장에 소설 조건만 더한 것. `targets` 는 휘발성 함수(`gen_random_uuid()`)를 담아 한 번만 계산되므로
# INSERT 와 UPDATE 가 같은 묶음 id 를 본다. 묶음 INSERT 와 화 UPDATE 를 한 문장에 두는 것은 FK 검사가 문장 끝에 돌기
# 때문에 가능하다.
_BACKFILL_SQL = text(
    """
WITH targets AS (
    SELECT
        c.id AS chapter_id,
        gen_random_uuid() AS batch_id,
        c.novel_id,
        COALESCE((SELECT max(b.ordinal) FROM novel_batches b WHERE b.novel_id = c.novel_id), 0)
            + row_number() OVER (PARTITION BY c.novel_id ORDER BY c.ordinal) AS ordinal,
        c.start_message_id,
        c.start_message_created_at,
        c.end_message_id,
        c.end_message_created_at,
        c.assistant_message_count,
        c.source_hash,
        c.created_at
    FROM novel_chapters c
    WHERE c.batch_id IS NULL AND c.novel_id = :novel_id
),
inserted AS (
    INSERT INTO novel_batches (
        id, novel_id, ordinal, start_message_id, start_message_created_at, end_message_id, end_message_created_at,
        assistant_message_count, source_hash, target_episode_count, created_at
    )
    SELECT
        batch_id, novel_id, ordinal, start_message_id, start_message_created_at, end_message_id, end_message_created_at,
        assistant_message_count, source_hash, 1, created_at
    FROM targets
)
UPDATE novel_chapters c
SET batch_id = t.batch_id, episode_index = 0
FROM targets t
WHERE c.id = t.chapter_id
"""
)


async def ensure_batches(db: AsyncSession, novel_id: uuid.UUID) -> bool:
    """소설 `novel_id` 의 빈 묶음을 지우고 묶음 없는 화를 묶음에 넣는다. 고칠 것이 있었으면 True. 커밋은 호출자가 한다.

    고칠 것이 있는지는 잠금 없이 먼저 본다 — 대부분의 소설은 고칠 것이 없고, 상세 조회마다 사용자 행을 잠그면 같은
    사용자의 차감·환불과 줄을 서게 된다. 고칠 것이 있으면 사용자 행을 잠근 뒤 고친다: 두 요청이 동시에 같은 화를 채우면
    같은 묶음 번호를 두 번 쓰려다 유니크 위반이 나고, 묶음을 만드는 성공 저장도 사용자 행을 먼저 잡으므로 둘이 줄을 선다.
    잠근 뒤의 문장은 그때까지 커밋된 상태를 다시 보므로, 앞 요청이 이미 고쳤으면 아무것도 하지 않는다."""
    unbatched = exists().where(NovelChapter.novel_id == novel_id, NovelChapter.batch_id.is_(None))
    empty = exists().where(
        NovelBatch.novel_id == novel_id,
        ~exists().where(NovelChapter.batch_id == NovelBatch.id),
    )
    if not await db.scalar(select(or_(unbatched, empty))):
        return False
    user_id = await db.scalar(select(Novel.user_id).where(Novel.id == novel_id))
    if user_id is None or not await _lock_user(db, user_id):
        return False
    await db.execute(_DROP_EMPTY_BATCHES_SQL, {"novel_id": novel_id})
    await db.execute(_BACKFILL_SQL, {"novel_id": novel_id})
    return True
