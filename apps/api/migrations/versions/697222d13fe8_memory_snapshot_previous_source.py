"""memory snapshot previous source

Revision ID: 697222d13fe8
Revises: c328445d4c2d
Create Date: 2026-09-28 13:00:02.637450

요약 스냅샷에 되돌리기 한 단계의 출처 컬럼을 더한다. 뜻은 `ChatRoomMemorySnapshot` docstring에
있다. 기본값 없는 NULL 컬럼이라 기존 행을 다시 쓰지 않는다. 채우는 백필은 없다 — 이 컬럼이
생기기 전에 사용자가 고친 행은 직전 출처를 알 수 없다.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '697222d13fe8'
down_revision: str | Sequence[str] | None = 'c328445d4c2d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('chat_room_memory_snapshots', sa.Column('previous_source', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('chat_room_memory_snapshots', 'previous_source')
