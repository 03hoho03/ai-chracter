"""report reason minor safety

Revision ID: 80f5dda86e33
Revises: c4a7e2d91b3f
Create Date: 2026-10-05 11:53:07.111505

작품·댓글 신고 사유 `report_reason_category` 에 `MINOR_SAFETY`(아동·청소년 관련)를 더한다. 이 타입은
`reports.reason_category` 와 `comment_reports.reason_category` 두 컬럼이 함께 쓴다. autogenerate 가 기존 타입의
멤버 추가를 감지하지 못해 손으로 썼다.

`ADD VALUE` 는 트랜잭션 안에서 실행되지만 같은 트랜잭션에서 새 값을 쓸 수 없다. 마이그레이션 전체가 한 트랜잭션으로
돌므로 이 리비전과 뒤따르는 리비전은 `MINOR_SAFETY` 를 쓰는 데이터 이관을 하면 안 된다.

downgrade 는 Postgres 에 `DROP VALUE` 가 없어 타입을 다시 만든다. 새 사유로 접수된 신고를 지우지 않고 `OTHER` 로
옮긴 뒤 바꾼다 — 롤백 때 신고 기록 자체가 사라지면 안 되고, 옮기지 않으면 `USING` 캐스트가 실패한다. 다시 올려도
원래 사유로 돌아오지 않는다.
"""
from typing import Union
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '80f5dda86e33'
down_revision: str | Sequence[str] | None = 'c4a7e2d91b3f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("reports", "comment_reports")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE report_reason_category ADD VALUE 'MINOR_SAFETY' AFTER 'ADULT'")


def downgrade() -> None:
    """Downgrade schema."""
    for table in _TABLES:
        op.execute(
            f"UPDATE {table} SET reason_category = 'OTHER' WHERE reason_category = 'MINOR_SAFETY'"
        )
    op.execute("ALTER TYPE report_reason_category RENAME TO report_reason_category_old")
    sa.Enum("ADULT", "COPYRIGHT", "HATE", "SPAM", "OTHER", name="report_reason_category").create(
        op.get_bind()
    )
    for table in _TABLES:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN reason_category TYPE report_reason_category "
            "USING reason_category::text::report_reason_category"
        )
    op.execute("DROP TYPE report_reason_category_old")
