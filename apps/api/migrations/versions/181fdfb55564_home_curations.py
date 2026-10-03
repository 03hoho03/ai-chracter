"""home curations

Revision ID: 181fdfb55564
Revises: ade2c1031e12
Create Date: 2026-10-04 00:45:55.300599

홈 첫 화면에 유형마다 한 편씩 거는 운영자 지정작을 담는 `home_curations` 를 만든다. 추가만 하는 리비전이라 기존
행·컬럼을 바꾸지 않고, 처음엔 비어 있다(지정 없음 = 홈에 섹션 없음).

유형 칸은 `contents.type` 이 이미 쓰는 `content_type` 타입을 재사용하므로 여기에서 만들지도(`create_type=False`)
지우지도 않는다 — downgrade 에서 지우면 그 타입을 쓰는 `contents` 때문에 실패한다.

`content_id` 에 `ondelete` 를 두지 않는 이유: 지정은 공개 목록에 실린(발행본이 있는) 작품만 받고, 작품 행을 지우는
경로는 발행된 적 없는 초안 삭제뿐이라 지정 작품이 지워질 일이 없다. 그런 경로가 생기면 조용히 비는 대신 FK 위반으로
드러나는 편이 낫다.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '181fdfb55564'
down_revision: str | Sequence[str] | None = 'ade2c1031e12'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('home_curations',
    sa.Column('content_type', postgresql.ENUM('CHARACTER', 'STORY', name='content_type', create_type=False), nullable=False),
    sa.Column('content_id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['content_id'], ['contents.id'], ),
    sa.PrimaryKeyConstraint('content_type')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('home_curations')
