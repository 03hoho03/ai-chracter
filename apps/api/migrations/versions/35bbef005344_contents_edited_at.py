"""contents edited_at

Revision ID: 35bbef005344
Revises: 65205c06e037
Create Date: 2026-10-26 18:00:00.000000

작가가 자기 작품(캐릭터·스토리)을 마지막으로 바꾼 시각 `contents.edited_at` 을 더하고, 작가별 최근 편집 순으로 넘기는
인덱스 `(creator_user_id, edited_at DESC, id DESC)` 를 만든다. 기존 `contents.updated_at` 은 건드리지 않는다 — 그 칸을
미는 코드가 없어 사실상 생성 시각이고, `/me/drafts` 커서가 "넘기는 도중 행이 움직이지 않는다"에 기대기 때문이다.

칸은 `NOT NULL DEFAULT now()` 로 붙인다. `now()` 는 STABLE 이라 Postgres 11 이상에서 표를 다시 쓰지 않고 카탈로그
기본값으로 붙는다. 기본값은 영구히 둔다 — 칸을 모르는 쓰기 경로(옛 이미지의 작품 생성·시드)가 계속 기본값에 기댄다.

백필: 각 작품을 `GREATEST(created_at, 그 작품 버전들의 최신 published_at)` 로 채운다. 발행 이력이 없으면 최신 발행
시각이 NULL 이고 `GREATEST` 는 NULL 을 무시하므로 생성 시각이 된다. 한계 — 자동저장 시각은 어디에도 남아 있지 않아
"마지막 발행 뒤 고친 수정본"도 마지막 발행 시각으로 들어간다. 버전 행에는 수정 시각 칸이 없어 더 나은 신호가 없다.
버전별 최신 발행 시각은 상관 하위 쿼리 대신 GROUP BY 조인으로 구한다 — `content_versions.content_id` 에 인덱스가 없어
상관 하위 쿼리는 작품마다 버전 표를 순차 스캔한다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다(이 저장소 리비전 관례). 잠금 — `ADD COLUMN` 이 `contents` 에
ACCESS EXCLUSIVE 를 잡고, 같은 트랜잭션이라 그 잠금을 커밋까지 쥔다. 그래서 백필 UPDATE 와 일반 `CREATE INDEX`
(트랜잭션 안 — `CONCURRENTLY` 는 이 체인과 맞지 않는다)가 끝날 때까지 `contents` 의 쓰기(조회수 증가 포함)뿐 아니라
읽기(SELECT)도 모두 기다린다. 행 수가 작아 그 구간이 짧다는 데 기댄다.

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 옛 코드의 INSERT 는 칸을 몰라 기본값이 채우고, 옛 코드는 칸을 밀지
않을 뿐이다. 그 구간에 저장된 편집은 순서에 늦게 반영되고 다음 저장에서 바로잡힌다.

**downgrade** — 인덱스와 칸을 지운다. 칸을 읽는 코드를 먼저 내리고 그 뒤에 내린다(반대 순서면 새 코드가 없는 칸을
읽어 500).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "35bbef005344"
down_revision: str | Sequence[str] | None = "65205c06e037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 각 작품의 편집 시각을 생성 시각과 최신 발행 시각 중 늦은 것으로 채운다. 테스트가 이 문장을 그대로 실행해 단언한다.
BACKFILL_EDITED_AT_SQL = """
UPDATE contents AS c
SET edited_at = GREATEST(c.created_at, v.max_pub)
FROM (
  SELECT ct.id, max(cv.published_at) AS max_pub
  FROM contents ct LEFT JOIN content_versions cv ON cv.content_id = ct.id
  GROUP BY ct.id
) AS v
WHERE v.id = c.id
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "contents",
        sa.Column("edited_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.execute(BACKFILL_EDITED_AT_SQL)
    op.create_index(
        "ix_contents_creator_user_id_edited_at",
        "contents",
        ["creator_user_id", sa.literal_column("edited_at DESC"), sa.literal_column("id DESC")],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_contents_creator_user_id_edited_at", table_name="contents")
    op.drop_column("contents", "edited_at")
