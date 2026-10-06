"""endings priority stat def entity id

Revision ID: a966fc016bf1
Revises: 3bb2cc159b6d
Create Date: 2026-10-06 15:59:36.322986

엔딩에 "우선 스탯"을 더한다. 같은 턴에 규칙을 통과한 엔딩 가운데 이 칸을 채운 것끼리는 그 스탯 값이 가장 높은 것만
판정한다 — 목록 순서만으로는 호감이 가장 높은 루트가 아니라 목록 위쪽 루트가 열린다. 기존 행은 NULL 로 남아 지금처럼
목록 순서 자리에서 판정되므로 백필하지 않는다.

nullable 이고 `server_default` 를 두지 않는다. 이 컬럼을 모르는 이전 API 이미지로 되돌려도 그 코드의 엔딩 INSERT(저장·발행
복제·시드)는 이 컬럼을 빼고 넣어 NULL 이 되므로 실패하지 않는다. 다만 그 이미지로 발행·편집 취소를 하면 복제본에서 값이
사라지므로, 되돌릴 때는 이미지를 먼저 내리고 downgrade 한다. downgrade 는 컬럼과 값을 함께 지운다.

엔딩 규칙의 스탯 참조와 같이 `StatDef.entity_id` 를 가리키므로 FK 를 걸지 않는다(물리 id 가 아니라 버전을 넘는 id 다).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a966fc016bf1'
down_revision: str | Sequence[str] | None = '3bb2cc159b6d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('endings', sa.Column('priority_stat_def_entity_id', sa.Uuid(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('endings', 'priority_stat_def_entity_id')
