"""legal documents effective_at, withdrawn status

Revision ID: 1c4ff252c34a
Revises: 49b68a8a681e
Create Date: 2026-10-18 12:00:00.000000

법무 문서 게시본에 **시행 시각**(`effective_at`)을 더한다. 지금까지는 게시하는 순간 현행이 되어 약관 제4조 제2항("시행일
전에 게시")을 구조적으로 지킬 수 없었다. 이제 현행판은 "게시본 중 시행 시각이 지난 것 가운데 가장 늦게 시행된 것"이고,
시행 시각이 미래인 게시본은 시행 예정 판이다.

**백필**: 기존 게시본의 `effective_at` 은 `published_at` 으로 채운다. 지금까지 게시본은 게시 즉시 현행이 됐으므로 그 시각이
실제로 현행이 된 시각이다. 백필 뒤 순서(시행 시각, 같으면 게시 시각)는 옛 코드의 순서(게시 시각)와 같다.

**제약**: 초안이 아닌 행(게시본·철회본)은 `effective_at` 이 반드시 있다 — CHECK `ck_legal_documents_effective_at_released`.
앱 검증만 두지 않은 이유: 시행 시각이 비어 있는 게시본은 현행 조회(`effective_at <= now`)에서 조용히 빠져 영영 현행이 되지
못한다. 그런 행이 생기는 길(배포 겹침 동안 옛 이미지가 칸을 모르고 게시하는 경우, DB 직접 입력)을 쓰기 시점에 막는 쪽이
낫다. 옛 이미지의 게시는 이 CHECK 에 걸려 `IntegrityError` 가 나고, 옛 게시 경로는 그것을 "이미 존재하는 버전" 409 로
바꾸므로 500 이 아니다. 다만 옛 색이 서빙하는 동안에는 다시 눌러도 같은 CHECK 에 걸려 계속 409 이고, 문구도 원인과 다르다.
새 색으로 바뀐 뒤 다시 게시하면 된다.

**철회 상태**: `status` 는 Text 라 `withdrawn` 값만 새로 쓴다. 시행 전에 철회한 판은 행을 지우지 않고 이 상태로 남긴다.
`(kind, version)` 부분 유니크 인덱스를 게시본뿐 아니라 철회본까지 덮도록 넓힌다(이름도 `..._released` 로 바꾼다). 철회한
판의 버전 문자열은 이미 공지로 나갔을 수 있다 — 같은 버전 이름으로 다른 본문을 다시 게시하면 공지·감사 로그·어드민 이력에서
두 판을 가를 수 없게 된다. 고친 판은 새 버전 이름으로 다시 예약한다.

**옛 이미지가 이 스키마 위에서 도는 구간**: 옛 코드는 `effective_at` 을 모르고 `status = 'published'` 만 본다. 철회본은 옛
코드에 보이지 않는다. **시행 예정 판은 옛 코드에 "최신 게시본"으로 보인다** — 겹침 동안 새 코드가 예약 게시를 하지 않으면
문제가 없다. 이미지만 되돌릴 때도 같다: 되돌리기 전에 시행 예정 판을 모두 철회한다.

**롤백 순서**: 시행 예정 판을 어드민에서 철회 → 이 리비전 파일이 있는 이미지로 `downgrade` → 이미지 되돌리기. 시행 예정 판이
남아 있으면 `downgrade()` 는 아무것도 바꾸지 않고 `RuntimeError` 로 멈춘다(되돌리면 그 판이 옛 코드에서 즉시 현행이 된다).
downgrade 는 `effective_at` 을 버린다. 시행 시각이 게시 시각보다 늦었던 판(예약했다가 시행된 판)과 그 사이에 즉시 게시된 판이
같이 있으면 옛 코드는 게시 시각 순서로 현행을 고르므로 현행판이 바뀔 수 있다. 철회본은 옛 인덱스(게시본만) 밖이라 남아도
옛 코드에 영향이 없다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1c4ff252c34a"
down_revision: str | Sequence[str] | None = "49b68a8a681e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 공개 조회·재동의 게이트가 매 요청 이 테이블을 읽는다 — 오래 걸린 트랜잭션 뒤에서 ALTER 락을 기다리며 그 읽기를 줄
    # 세우지 않게, 못 잡으면 마이그레이션이 실패하게 한다.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("legal_documents", sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE legal_documents SET effective_at = published_at WHERE status = 'published'")
    op.create_check_constraint(
        "ck_legal_documents_effective_at_released",
        "legal_documents",
        "status = 'draft' OR effective_at IS NOT NULL",
    )
    op.drop_index(
        "ix_legal_documents_kind_version_published",
        table_name="legal_documents",
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_index(
        "ix_legal_documents_kind_version_released",
        "legal_documents",
        ["kind", "version"],
        unique=True,
        postgresql_where=sa.text("status IN ('published', 'withdrawn')"),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    scheduled = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM legal_documents WHERE status = 'published' AND effective_at > now()")
    )
    if scheduled:
        raise RuntimeError(
            f"시행 예정 판이 {scheduled}건 있다. 되돌리면 옛 코드에서 즉시 현행이 되므로 어드민에서 먼저 철회한다."
        )
    op.drop_index(
        "ix_legal_documents_kind_version_released",
        table_name="legal_documents",
        postgresql_where=sa.text("status IN ('published', 'withdrawn')"),
    )
    op.create_index(
        "ix_legal_documents_kind_version_published",
        "legal_documents",
        ["kind", "version"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )
    op.drop_constraint("ck_legal_documents_effective_at_released", "legal_documents", type_="check")
    op.drop_column("legal_documents", "effective_at")
