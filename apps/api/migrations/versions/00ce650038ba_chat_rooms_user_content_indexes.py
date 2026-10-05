"""chat_rooms user content indexes

Revision ID: 00ce650038ba
Revises: 7d0a4e0b08cf
Create Date: 2026-10-05 15:22:09.722451

`chat_rooms` 를 `user_id`·`content_id` 로 거르는 쿼리(같은 작품의 내 방들, 내 방 목록, 탈퇴, 작품 접근 판정,
버전 일괄 승격)가 지금은 전부 순차 스캔이다 — Postgres 는 FK 열에 인덱스를 자동으로 만들지 않는다.
`(user_id, content_id)` 복합 하나가 두 열을 함께 거르는 쿼리와 `user_id` 만 거르는 쿼리를 함께 받고,
`content_id` 만 거르는 쿼리는 단일 인덱스가 받는다. 일반 `CREATE INDEX`(트랜잭션 안)라 생성 동안
`chat_rooms` 쓰기가 막히지만 운영 행 수가 작아 짧다. `CONCURRENTLY` 는 트랜잭션 밖에서만 돌아 이
마이그레이션 체인과 맞지 않는다.
"""
from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '00ce650038ba'
down_revision: str | Sequence[str] | None = '7d0a4e0b08cf'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index('ix_chat_rooms_content_id', 'chat_rooms', ['content_id'], unique=False)
    op.create_index('ix_chat_rooms_user_id_content_id', 'chat_rooms', ['user_id', 'content_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chat_rooms_user_id_content_id', table_name='chat_rooms')
    op.drop_index('ix_chat_rooms_content_id', table_name='chat_rooms')
