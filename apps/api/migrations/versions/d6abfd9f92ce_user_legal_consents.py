"""user legal consents history

Revision ID: d6abfd9f92ce
Revises: fc3ca58a473b
Create Date: 2026-10-18 20:10:00.000000

회원의 법무 동의를 판·동의 단위마다 쌓는 이력 테이블 `user_legal_consents` 를 만든다. `users` 의 버전·동의 시각 칸은
마지막 동의만 남기고 덮어쓰여, 과거 판에 동의했다는 기록이 사라졌다. 칸은 회원, 게시본 id, 동의 단위(`terms`·
`collection`·`transfer`), 동의 시각뿐이다 — 가입인지 재동의인지 가르는 칸은 두지 않는다(처리방침이 수집 항목으로 적은
것은 동의 단위별 동의 시각과 동의 당시 문서 버전이다).

**FK·인덱스**: 두 FK 모두 `ondelete` 를 두지 않는다. 회원 행과 게시본 행은 지우지 않으므로(탈퇴는 가명화, 철회는 상태)
연쇄 삭제가 일어날 일이 없고, 탈퇴 파기는 `erase_account` 가 회원 행을 잠근 채 이 테이블을 직접 지운다. CASCADE 를 두면
회원 행 잠금 순서와 무관한 삭제 경로가 생긴다. 인덱스는 `user_id` 하나다(파기의 `DELETE ... WHERE user_id` 와 회원별
조회). 게시본 id 쪽은 게시본을 지우지 않으므로 FK 검사용 인덱스가 필요 없다.

**백필**: 탈퇴하지 않은 회원(`deleted_at IS NULL`)마다 `users` 의 약관·처리방침·국외이전 버전을 같은 문서의 게시본
(`status = 'published'`)에서 찾아 1행씩 넣는다. 시각은 각 `*_agreed_at` 이다. 버전이나 시각이 비었거나 게시본에서 찾지
못하면 그 행은 만들지 않는다(가리킬 판이 없다). 탈퇴 회원은 넣지 않는다 — 탈퇴하면 이력을 파기하므로 넣으면 바로 파기
대상이다. 운영 실측(2026-10-18)에서 활성 회원의 버전은 모두 게시본에 있었고, 못 찾은 건수는 경고 로그로 남긴다.

**이전 이미지가 이 스키마 위에서 도는 구간**: 이전 코드는 이 테이블을 모른다. 겹침 동안 이전 색이 받은 가입·재동의는
`users` 칸만 쓰고 이력 행을 남기지 않는다. 회원 행을 지우지 않으므로 FK 때문에 실패할 쓰기도 없다.

**롤백**: downgrade 는 테이블을 지운다. 쌓인 이력은 되살리지 못한다(`users` 칸의 마지막 동의만 남는다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d6abfd9f92ce"
down_revision: str | Sequence[str] | None = "fc3ca58a473b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

# (동의 단위, 문서 종류, 버전 칸, 동의 시각 칸)
_CONSENT_COLUMNS = (
    ("terms", "terms", "terms_version", "terms_agreed_at"),
    ("collection", "privacy", "privacy_version", "privacy_agreed_at"),
    ("transfer", "privacy", "transfer_version", "transfer_agreed_at"),
)


def backfill_consent_history(connection: sa.Connection) -> int:
    """활성 회원의 `users` 동의 칸으로 이력을 1행씩 넣고, 버전이 있는데 게시본에서 찾지 못해 건너뛴 건수를 돌려준다."""
    skipped = 0
    for consent, kind, version_column, agreed_column in _CONSENT_COLUMNS:
        connection.execute(
            sa.text(
                "INSERT INTO user_legal_consents (id, user_id, legal_document_id, consent, consented_at) "
                f"SELECT gen_random_uuid(), u.id, d.id, :consent, u.{agreed_column} "
                "FROM users u JOIN legal_documents d "
                f"ON d.kind = :kind AND d.status = 'published' AND d.version = u.{version_column} "
                f"WHERE u.deleted_at IS NULL AND u.{agreed_column} IS NOT NULL"
            ),
            {"consent": consent, "kind": kind},
        )
        skipped += connection.scalar(
            sa.text(
                f"SELECT count(*) FROM users u WHERE u.deleted_at IS NULL AND u.{version_column} IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM legal_documents d "
                f"WHERE d.kind = :kind AND d.status = 'published' AND d.version = u.{version_column})"
            ),
            {"kind": kind},
        ) or 0
    return skipped


def upgrade() -> None:
    # 새 테이블의 FK 를 만들면 `users`·`legal_documents` 에 락이 걸린다. 매 요청이 읽는 두 테이블이라, 오래 걸린 트랜잭션
    # 뒤에서 그 락을 기다리며 읽기를 줄 세우지 않게 못 잡으면 마이그레이션이 실패하게 한다.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "user_legal_consents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("legal_document_id", sa.Uuid(), nullable=False),
        sa.Column("consent", sa.Text(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("consent IN ('terms', 'collection', 'transfer')", name="ck_user_legal_consents_consent"),
        sa.ForeignKeyConstraint(["legal_document_id"], ["legal_documents.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_legal_consents_user_id"), "user_legal_consents", ["user_id"], unique=False)

    skipped = backfill_consent_history(op.get_bind())
    if skipped:
        logger.warning("user_legal_consents: 게시본에서 버전을 찾지 못해 이력을 만들지 않은 동의 %d건", skipped)


def downgrade() -> None:
    # 테이블을 지우면 FK 가 가리키는 `users`·`legal_documents` 에도 락이 걸린다 — upgrade 와 같은 이유로 대기 상한을 둔다.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index(op.f("ix_user_legal_consents_user_id"), table_name="user_legal_consents")
    op.drop_table("user_legal_consents")
