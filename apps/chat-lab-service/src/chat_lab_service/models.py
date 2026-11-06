"""표 둘 — 판 표와 접근 기록. 마이그레이션이 같은 정의를 만들고 `alembic check` 가 둘을 대조한다.

`alembic check` 는 CHECK 제약을 비교하지 않으므로 여기 CHECK 를 고치면 마이그레이션도 손으로 맞춘다.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

bundle_versions = Table(
    "bundle_versions",
    metadata,
    # 판 번호는 칸이 아니라 읽을 때 런마다 이 순서로 매긴다 — 지운 판도 번호를 차지해 남은 판 번호가 바뀌지 않는다. 같은 런의
    # 올리기는 런 잠금으로 줄을 서서(`bundles.store_version`) 런 안의 이 순서가 커밋 순서와 같다.
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("run_id", Text, nullable=False),
    # 압축 푼 JSON 바이트의 sha256.
    Column("sha256", Text, nullable=False),
    # 올린 gzip 그대로. 지우면 비운다.
    Column("body", LargeBinary, nullable=True),
    Column("compressed_size", Integer, nullable=False),
    Column("uncompressed_size", Integer, nullable=False),
    Column("contract_version", Integer, nullable=False),
    Column("raw", Boolean, nullable=False),
    # 묶음의 `detail.run` 그대로 — 웹 목록이 그 칸을 거의 다 읽어, 칸으로 쪼개면 측정 서버가 칸을 더할 때마다 마이그레이션이
    # 생긴다. 조회 조건에는 쓰지 않는 표시용이다.
    Column("run_item", JSONB, nullable=False),
    Column("source_commit", Text, nullable=False),
    Column("source_dirty", Boolean, nullable=False),
    Column("provenance", JSONB, nullable=False),
    Column("uploaded_by", Text, nullable=False),
    Column("uploaded_at", DateTime(timezone=True), nullable=False),
    Column("deleted_by", Text, nullable=True),
    Column("deleted_at", DateTime(timezone=True), nullable=True),
    # 같은 내용은 런마다 한 판. 이 색인이 런 id 앞자리 조회도 덮는다.
    UniqueConstraint("run_id", "sha256", name="uq_bundle_versions_run_id_sha256"),
    CheckConstraint("char_length(run_id) BETWEEN 1 AND 1024", name="ck_bundle_versions_run_id_length"),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_bundle_versions_sha256_hex"),
    CheckConstraint("compressed_size > 0", name="ck_bundle_versions_compressed_size_positive"),
    CheckConstraint("uncompressed_size > 0", name="ck_bundle_versions_uncompressed_size_positive"),
    CheckConstraint("source_commit ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'", name="ck_bundle_versions_source_commit_hex"),
    # 지운 이와 지운 때는 짝으로 남고, 지운 판만 본문이 빈다.
    CheckConstraint("(deleted_at IS NULL) = (deleted_by IS NULL)", name="ck_bundle_versions_deleted_pair"),
    CheckConstraint("(body IS NULL) = (deleted_at IS NOT NULL)", name="ck_bundle_versions_body_only_when_live"),
)

access_log = Table(
    "access_log",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("at", DateTime(timezone=True), nullable=False),
    # none = 토큰 없음·무효(또는 상태 확인), unknown = 유효한 토큰인데 email·common_name 이 정확히 하나가 아님.
    Column("identity_kind", Text, nullable=False),
    # 사람은 email, 서비스 토큰은 common_name. none·unknown 은 비운다.
    Column("identity", Text, nullable=True),
    Column("method", Text, nullable=False),
    # 경로 원문이 아니라 경로 틀 — 맞는 라우트가 없는 경로에는 아무 입력이나 들어올 수 있다.
    Column("route", Text, nullable=False),
    Column("run_id", Text, nullable=True),
    Column("sha256", Text, nullable=True),
    # 원문(프롬프트 전문)이 든 묶음 본문을 내줬는가.
    Column("raw_served", Boolean, nullable=False, server_default=false()),
    Column("status", SmallInteger, nullable=False),
    Column("reason", Text, nullable=True),
    Column("client_ip", Text, nullable=True),
    CheckConstraint("identity_kind IN ('none', 'human', 'service', 'unknown')", name="ck_access_log_identity_kind"),
    Index("ix_access_log_at", "at"),
)
