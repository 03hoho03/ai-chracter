"""assets crop and animated variants

Revision ID: c60f5b9b11bc
Revises: 2975c3a6fa6f
Create Date: 2026-10-19 18:25:53.623680

움직이는 대표 이미지(GIF)를 위해 자산 행에 두 칸을 더한다.

- `crop`: 서버가 모든 프레임에 거는 크롭 영역. 화면의 크롭 모달은 canvas 로 한 장만 그려 움직임을 지우므로, GIF 는
  원본과 영역을 따로 올린다. 정지 그림은 NULL.
- `animated_variants_ready`: 움직이는 변형을 백그라운드에서 다 만들었는가. 기본값 false.

추가만 하는 컬럼이라 배포가 겹치는 동안 옛 코드도 그대로 돈다 — 옛 INSERT 는 `crop` 을 NULL, `animated_variants_ready`
를 기본값 false 로 채운다. 그래서 `server_default` 는 떼지 않는다. 떠 있는 API 가 읽는 테이블의 ALTER 라 잠금을 오래
기다리지 않게 5초 상한을 건다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c60f5b9b11bc"
down_revision: str | Sequence[str] | None = "2975c3a6fa6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("assets", sa.Column("crop", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column(
        "assets",
        sa.Column("animated_variants_ready", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("assets", "animated_variants_ready")
    op.drop_column("assets", "crop")
