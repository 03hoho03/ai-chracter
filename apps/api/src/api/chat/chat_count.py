"""작품의 대화수(`contents.chat_count`) 집계. 대화수는 "그 작품과 대화를 시작한 사람 수" 이고 작가 본인은 빠진다.

방을 만드는 함수가 같은 트랜잭션에서 부른다. 라우터를 import 하지 않는다."""

import uuid

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.content import Content, ContentChatParticipant


async def record_chat_participant(db: AsyncSession, content: Content, user_id: uuid.UUID) -> None:
    """`user_id` 가 `content` 와 처음 대화를 시작했으면 쌍을 기록하고 대화수를 1 올린다.

    "처음인가" 는 기록 표의 복합 PK 가 판정한다 — 삽입이 충돌로 무시되면 이미 센 사람이다. 같은 사용자의 두 요청은
    호출부가 먼저 잡는 회원 행 잠금으로 직렬화되고, 서로 다른 사용자의 두 요청은 쌍이 달라 둘 다 들어간다.

    증가는 읽은 값에 1을 더해 쓰지 않고 SQL 안에서 상대값으로 올린다 — 서로 다른 사용자가 동시에 시작하면 둘 다 같은
    옛 값을 읽었을 수 있고, 그 값으로 덮어쓰면 한 번이 사라진다. 이 UPDATE 가 작품 행을 잠그므로 회원 행을 먼저
    잠그는 저장소의 순서(회원 → 작품)를 지키려면 호출부가 회원 잠금 뒤에 불러야 한다."""
    if user_id == content.creator_user_id:
        return
    inserted = await db.scalar(
        pg_insert(ContentChatParticipant)
        .values(content_id=content.id, user_id=user_id)
        .on_conflict_do_nothing()
        .returning(ContentChatParticipant.user_id)
    )
    if inserted is None:
        return
    await db.execute(
        update(Content).where(Content.id == content.id).values(chat_count=Content.chat_count + 1)
    )
