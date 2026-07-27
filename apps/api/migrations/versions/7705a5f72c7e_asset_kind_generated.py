"""asset_kind_generated

Revision ID: 7705a5f72c7e
Revises: ec416a217f5d
Create Date: 2026-07-27 15:58:47.872355

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7705a5f72c7e'
down_revision: Union[str, Sequence[str], None] = 'ec416a217f5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # autogenerate does not detect new enum member additions to an existing
    # Postgres type, so this is written by hand (tasks/prd-image-generation.md US-001).
    op.execute("ALTER TYPE asset_kind ADD VALUE 'GENERATED'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres has no ALTER TYPE ... DROP VALUE, so narrowing the enum back
    # requires recreating the type and re-pointing the column at it. This
    # fails if any row still has kind='generated' at downgrade time.
    op.execute("ALTER TYPE asset_kind RENAME TO asset_kind_old")
    sa.Enum("ORIGINAL", "BLURRED", "THUMBNAIL", name="asset_kind").create(op.get_bind())
    op.execute(
        "ALTER TABLE assets ALTER COLUMN kind TYPE asset_kind USING kind::text::asset_kind"
    )
    op.execute("DROP TYPE asset_kind_old")
