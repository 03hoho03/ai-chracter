"""novel serial lock and publication review

Revision ID: 6fbf1e9a65b8
Revises: e05462d680f0
Create Date: 2026-10-19 12:00:00.000000

소설에 연재권 잠금 칸 다섯을, 노벨 공개 행에 운영자 심사 칸 셋을 더하고, 이미 공개한 적이 있는 소설을 연재권 잠금으로
채운다.

**연재권 잠금 칸**(`novels`): 잠긴 시각(`serial_locked_at`), 그때 원작의 소설화 허락 사본(`serial_lock_permission`, NULL 은
알 수 없음 또는 원작 행 없음), 그때 원작 버전 id(`serial_lock_content_version_id`, FK 없음 — 원작이 지워져도 소설은 남는다),
그때 효력이 있던 약관 판(`serial_lock_terms_version`, 약관 게시본이 없던 때면 NULL), 출처(`serial_lock_source`, 첫 공개
`first_publish` / 이 마이그레이션 `backfill`). 집필권 잠금 칸과 같은 꼴이다. CHECK 셋: 허락 값 범위(NULL 통과), 출처 값
범위, 시각과 출처는 함께 있거나 함께 없다.

**심사 칸**(`novel_publications`): 심사 상태(`review_status`, NULL 은 심사 없이 공개된 행 / `pending` / `approved` /
`rejected`), 반려 사유(`review_reason`, 작가에게 그대로 보인다), 심사한 시각(`reviewed_at`). CHECK 셋: 상태 값 범위, 반려
행에는 사유가 있다, 대기·반려 행의 공개 범위는 `withdrawn` 이다. 마지막 CHECK 는 "심사 칸을 모르는 코드가 읽어도 대기·반려
행이 독자에게 나가지 않는다"는 전제를 DB 가 지키게 한다. 그 대가로 대기·반려 행을 공개로 돌리는 쓰기(승인, 그리고 심사를
끈 상태에서의 재신청)는 공개 범위와 심사 칸을 한 UPDATE 문으로 바꿔야 한다 — 나눠 쓰면 첫 문장이 이 CHECK 에 걸린다.

여덟 칸 모두 NULL 허용이고 기본값이 없어 칸 추가는 메타데이터만 바꾼다. autogenerate 가 CHECK 를 다루지 않아 CHECK 여섯은
손으로 더했다.

**백필**: 공개 행이 있는 소설을 전부 잠근다 — 지금 공개 중인 것뿐 아니라 공개했다 거둔 것도. 이 칸 이전에는 승인 대기가
없어 모든 공개 행이 만들어지는 순간 독자에게 보였기 때문이다. 잠긴 시각은 그 공개 행의 첫 공개 시각, 약관 판은 그 시각에
효력이 있던 약관 게시본(시행 시각이 그 시각 이하인 것 가운데 시행 시각, 그다음 게시 시각이 가장 늦은 것 — 현행판 조회와
같은 정렬, 철회본·초안 제외)의 버전이다. 출처는 `backfill`, 허락 사본과 원작 버전은 NULL 이다 — 그때 값을 알 수 없다. 아직
잠기지 않은 소설과 심사 상태가 NULL 인 공개 행만 보므로 다시 돌려도 값이 바뀌지 않고, 심사를 켠 뒤에 돌려도 대기·반려
행(독자에게 보인 적 없는 글)을 잠그지 않는다. 그래서 옛 이미지가 다 내려간 뒤, 그리고 승인 심사를 켜기 직전에 같은
문장(`BACKFILL_SERIAL_LOCK_SQL`)을 한 번 더 돌려 그사이 옛 코드나 심사 꺼진 코드가 만든 첫 공개도 잠글 수 있다.

**옛 이미지가 이 스키마 위에서 도는 구간**: 옛 코드는 새 칸을 모른다. 소설·공개 행 INSERT 는 칸을 넘기지 않아 NULL 이 되고
CHECK 여섯을 모두 통과하며(심사 상태 NULL 은 공개 범위와 무관하게 통과), 첫 공개를 해도 잠금을 쓰지 않는다(위 재실행이
메운다).

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. `novels`·`novel_publications` 는 공개 소설을 읽는 요청마다 읽는 테이블이라,
오래 걸린 트랜잭션 뒤에서 락을 기다리는 동안 그 뒤의 읽기가 모두 줄을 서지 않게 못 잡으면 마이그레이션을 실패시킨다(체인
전체 롤백, 다시 돌리면 된다).

**downgrade**: CHECK 여섯과 칸 여덟을 지운다. 잠금·심사 기록을 잃는다 — 첫 공개가 남긴 허락·원작 버전·약관 판 사본과
운영자의 승인·반려·사유가 사라지고, 다시 올리면 백필이 출처 `backfill`·사본 NULL 로만 채운다. 잠금·심사 행이 있어도 멈추는
가드는 두지 않는다 — 테스트 스위트 끝의 `alembic downgrade base` 가 테스트가 커밋한 잠금·심사 행 하나 때문에 깨지기
때문이다. 대기·반려 행은 공개 범위 `withdrawn` 으로 남아 옛 코드에서 독자에게 보이지 않지만, 작가에게는 "거둠"으로 보이고
CHECK 도 함께 사라졌으므로 작가가 다시 열면 승인 없이 공개된다. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만
되돌린다 — 그때는 CHECK 가 남아 옛 코드의 다시 열기(공개 범위만 바꾸는 UPDATE)가 대기·반려 행에서 CHECK 위반(500)으로
멈추고, 승인 없이 공개되지는 않는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6fbf1e9a65b8"
down_revision: str | Sequence[str] | None = "e05462d680f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

BACKFILL_SERIAL_LOCK_SQL = """
UPDATE novels n
SET serial_locked_at = p.first_published_at,
    serial_lock_source = 'backfill',
    serial_lock_terms_version = (
      SELECT d.version FROM legal_documents d
      WHERE d.kind = 'terms' AND d.status = 'published' AND d.effective_at <= p.first_published_at
      ORDER BY d.effective_at DESC, d.published_at DESC
      LIMIT 1
    )
FROM novel_publications p
WHERE p.novel_id = n.id
  AND n.serial_locked_at IS NULL
  AND p.review_status IS NULL
"""


def backfill_serial_locks(connection: sa.Connection) -> int:
    """공개한 적이 있는데 아직 연재권이 잠기지 않은 소설을 잠그고, 잠근 소설 수를 돌려준다."""
    return connection.execute(sa.text(BACKFILL_SERIAL_LOCK_SQL)).rowcount


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("novels", sa.Column("serial_locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("novels", sa.Column("serial_lock_permission", sa.Text(), nullable=True))
    op.add_column("novels", sa.Column("serial_lock_content_version_id", sa.Uuid(), nullable=True))
    op.add_column("novels", sa.Column("serial_lock_terms_version", sa.Text(), nullable=True))
    op.add_column("novels", sa.Column("serial_lock_source", sa.Text(), nullable=True))
    op.add_column("novel_publications", sa.Column("review_status", sa.Text(), nullable=True))
    op.add_column("novel_publications", sa.Column("review_reason", sa.Text(), nullable=True))
    op.add_column("novel_publications", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_novels_serial_lock_permission",
        "novels",
        "serial_lock_permission IN ('forbidden', 'private', 'public')",
    )
    op.create_check_constraint(
        "ck_novels_serial_lock_source", "novels", "serial_lock_source IN ('first_publish', 'backfill')"
    )
    op.create_check_constraint(
        "ck_novels_serial_lock_complete", "novels", "(serial_locked_at IS NULL) = (serial_lock_source IS NULL)"
    )
    op.create_check_constraint(
        "ck_novel_publications_review_status",
        "novel_publications",
        "review_status IN ('pending', 'approved', 'rejected')",
    )
    op.create_check_constraint(
        "ck_novel_publications_review_reason",
        "novel_publications",
        "review_status IS DISTINCT FROM 'rejected' OR review_reason IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_novel_publications_review_hidden",
        "novel_publications",
        "review_status IS NULL OR review_status NOT IN ('pending', 'rejected') OR visibility = 'withdrawn'",
    )

    locked = backfill_serial_locks(op.get_bind())
    logger.warning("novels: 이미 공개한 적이 있는 소설 %d권을 연재권 잠금으로 채웠다", locked)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint("ck_novel_publications_review_hidden", "novel_publications", type_="check")
    op.drop_constraint("ck_novel_publications_review_reason", "novel_publications", type_="check")
    op.drop_constraint("ck_novel_publications_review_status", "novel_publications", type_="check")
    op.drop_constraint("ck_novels_serial_lock_complete", "novels", type_="check")
    op.drop_constraint("ck_novels_serial_lock_source", "novels", type_="check")
    op.drop_constraint("ck_novels_serial_lock_permission", "novels", type_="check")
    op.drop_column("novel_publications", "reviewed_at")
    op.drop_column("novel_publications", "review_reason")
    op.drop_column("novel_publications", "review_status")
    op.drop_column("novels", "serial_lock_source")
    op.drop_column("novels", "serial_lock_terms_version")
    op.drop_column("novels", "serial_lock_content_version_id")
    op.drop_column("novels", "serial_lock_permission")
    op.drop_column("novels", "serial_locked_at")
