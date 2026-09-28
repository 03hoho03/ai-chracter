"""chat room memory

Revision ID: 40cddd24c600
Revises: 39faf8e2e4bd
Create Date: 2026-09-28 07:08:38.764587

채팅방 기억의 저장 자리. 컬럼·테이블의 뜻은 `db/models/chat.py`의 `ChatRoom` 주석과
`ChatRoomMemorySnapshot` docstring에 있다 — 여기서 되풀이하지 않는다.

- `chat_rooms`에 사용자 노트·요약 상태 카운터·마지막 되감기 시각 컬럼 3개를 더한다. 앞의 둘은
  상수 기본값이 있는 NOT NULL이라 Postgres 11+에서 기존 행을 다시 쓰지 않는다(카탈로그만 바뀐다).
  그래도 `ADD COLUMN`은 `chat_rooms`에 AccessExclusive 잠금을 잡고 체인이 한 트랜잭션이라
  마이그레이션 끝까지 쥔다.
- 요약 스냅샷 테이블은 `chat_rooms`만 가리킨다. 커서 메시지에는 FK를 걸지 않는다(모델 docstring).
  FK에 `ondelete`를 주지 않는다(저장소 규약) — 지우는 순서는 호출부가 지킨다.
- `source` 허용값은 CHECK 제약이 아니라 코드·응답 스키마가 강제한다 — `alembic check`는 CHECK를
  비교하지 않아 모델과 어긋나도 모른다.

`alembic check`는 서버 기본값도 비교하지 않는다(`compare_server_default`를 켜지 않았다). 두 NOT NULL
컬럼의 기본값이 빠지면 ORM이 그 컬럼을 INSERT에서 빼므로 방을 만드는 모든 경로가 NOT NULL
위반으로 실패한다 — 방을 만드는 기존 테스트가 이 기본값을 지킨다.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '40cddd24c600'
down_revision: str | Sequence[str] | None = '39faf8e2e4bd'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'chat_room_memory_snapshots',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('chat_room_id', sa.Uuid(), nullable=False),
        sa.Column('cursor_created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cursor_message_id', sa.Uuid(), nullable=False),
        sa.Column('summary_text', sa.Text(), nullable=False),
        sa.Column('previous_text', sa.Text(), nullable=True),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['chat_room_id'], ['chat_rooms.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_chat_room_memory_snapshots_room_cursor',
        'chat_room_memory_snapshots',
        ['chat_room_id', 'cursor_created_at', 'cursor_message_id'],
        unique=False,
    )
    op.add_column('chat_rooms', sa.Column('memory_note', sa.Text(), server_default='', nullable=False))
    op.add_column('chat_rooms', sa.Column('memory_version', sa.Integer(), server_default='0', nullable=False))
    op.add_column('chat_rooms', sa.Column('memory_rolled_back_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('chat_rooms', 'memory_rolled_back_at')
    op.drop_column('chat_rooms', 'memory_version')
    op.drop_column('chat_rooms', 'memory_note')
    op.drop_index('ix_chat_room_memory_snapshots_room_cursor', table_name='chat_room_memory_snapshots')
    op.drop_table('chat_room_memory_snapshots')
