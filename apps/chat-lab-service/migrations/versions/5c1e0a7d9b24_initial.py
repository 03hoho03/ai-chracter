"""판 표와 접근 기록

Revision ID: 5c1e0a7d9b24
Revises:
Create Date: 2026-11-05 21:00:00

`alembic check` 는 CHECK 제약을 비교하지 않는다 — 여기 CHECK 는 `chat_lab_service.models` 와 손으로 맞춘다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5c1e0a7d9b24"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bundle_versions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=True),
        sa.Column("compressed_size", sa.Integer(), nullable=False),
        sa.Column("uncompressed_size", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("raw", sa.Boolean(), nullable=False),
        sa.Column("run_item", postgresql.JSONB(), nullable=False),
        sa.Column("source_commit", sa.Text(), nullable=False),
        sa.Column("source_dirty", sa.Boolean(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("uploaded_by", sa.Text(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "sha256", name="uq_bundle_versions_run_id_sha256"),
        sa.CheckConstraint("char_length(run_id) BETWEEN 1 AND 1024", name="ck_bundle_versions_run_id_length"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_bundle_versions_sha256_hex"),
        sa.CheckConstraint("compressed_size > 0", name="ck_bundle_versions_compressed_size_positive"),
        sa.CheckConstraint("uncompressed_size > 0", name="ck_bundle_versions_uncompressed_size_positive"),
        sa.CheckConstraint(
            "source_commit ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'", name="ck_bundle_versions_source_commit_hex"
        ),
        sa.CheckConstraint("(deleted_at IS NULL) = (deleted_by IS NULL)", name="ck_bundle_versions_deleted_pair"),
        sa.CheckConstraint("(body IS NULL) = (deleted_at IS NOT NULL)", name="ck_bundle_versions_body_only_when_live"),
    )
    op.create_table(
        "access_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("identity_kind", sa.Text(), nullable=False),
        sa.Column("identity", sa.Text(), nullable=True),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("raw_served", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("client_ip", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "identity_kind IN ('none', 'human', 'service', 'unknown')", name="ck_access_log_identity_kind"
        ),
    )
    op.create_index("ix_access_log_at", "access_log", ["at"])


def downgrade() -> None:
    op.drop_index("ix_access_log_at", table_name="access_log")
    op.drop_table("access_log")
    op.drop_table("bundle_versions")
