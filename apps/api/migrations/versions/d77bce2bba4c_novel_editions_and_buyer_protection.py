"""novel chapter editions and buyer protection

Revision ID: d77bce2bba4c
Revises: 0f82ea9f9fa5
Create Date: 2026-10-19 18:00:00.000000

노벨 화의 판 이력 표를 만들고, 소설에 숨김 칸을, 노벨 구매에 환급 사유 칸을 더하고, 구매의 "화·구매자 하나에 한 행" 유니크를
"화·구매자 하나에 미환급 행 하나" 부분 유니크로 넓힌다. 지금 공개 중인 판을 판 이력 첫 행으로 채운다.

**판 이력**(`novel_chapter_editions`, PK `(chapter_id, edition)`): 공개(처음·다시)마다 한 행 — 그 판의 개정 id, 제목·작가의
말 사본, 공개 시각. 화 공개본은 다시 공개할 때 덮이므로 산 사람이 산 때의 판을 다시 읽으려면 지난 판이 따로 있어야 한다.
소설·화·개정 FK 는 `ON DELETE CASCADE` 다 — 옛 코드의 소설·묶음 삭제와 탈퇴는 이 표를 모르고 개정 → 화 → 소설 순으로
지우는데, cascade 가 없으면 그 DELETE 가 FK 위반(500)이 된다. CHECK 하나: 판 번호는 1 이상.

**숨김**(`novels.hidden_at`): 노벨로 팔린 소설을 작가가 지운 시각. 산 사람이 계속 읽도록 소설을 남기고 작가에게서만 감춘다.
CHECK 하나: 숨긴 소설은 방 칸이 비어 있다(방의 소설 조회·같은 방의 새 소설 만들기가 방 칸으로 소설을 찾으므로, 남으면 숨긴
소설이 되살아난다).

**환급 사유**(`novel_purchases.refund_reason`): 게시자 삭제 `deleted` / 게시자 탈퇴 `publisher_withdrawn` / 노벨 이용제한
`novel_restricted` / 원작 이용제한 `source_restricted` / 원작 삭제 `source_deleted`. CHECK 둘: 값 범위(NULL 통과), 사유가
있으면 환급 시각도 있다. 이미 있는 환급 행은 NULL 로 두고 코드가 `deleted` 로 읽는다 — 이 칸 전에는 환급이 게시자 삭제뿐이었다.

**재구매 유니크**: 옛 `ux_novel_purchases_chapter_id_buyer_user_id`(전체 유니크)를 지우고 같은 두 칸에 `WHERE refunded_at IS
NULL` 부분 유니크 `ux_novel_purchases_unrefunded_chapter_buyer` 를 만든다. 환급된 구매는 소장이 아니라서, 그 화가 다시 열리면
같은 사람이 새 행으로 다시 산다. 미환급 행은 여전히 하나뿐이다. 이름을 바꾼 것은 모델과 이 파일 중 한쪽만 바뀌면 `alembic
check` 가 인덱스 이름 차이로 드러내게 하려는 것이다(인덱스 조건식만 다른 것은 비교한다는 보장이 없다).

**백필**: 화 공개본마다 그 판 번호·개정·제목·작가의 말·공개 시각으로 판 행 하나. 그 이전 판은 남아 있지 않아 재구성하지
않는다. `ON CONFLICT DO NOTHING` 이라 다시 돌려도 이미 있는 판 행을 바꾸지 않고 없는 판만 더한다. 그래서 옛 이미지가 다
내려간 뒤와 노벨 정책 스위치(`novel_public_policy_v2_enabled`)를 켜기 직전에 같은 문장(`BACKFILL_CHAPTER_EDITIONS_SQL`)을 한 번 더 돌려, 그사이 옛 코드가
다시 공개하며 판 행 없이 올린 판을 채운다. 심사 대기 중인 첫 공개의 공개본도 채운다 — 판 행을 쓰는 새 코드도 대기 공개본에
판 행을 쓰고, 반려·신청 취소가 공개본과 함께 그 판 행을 지운다.

**옛 이미지가 이 스키마 위에서 도는 구간**: 옛 코드는 새 표·새 칸을 모른다. 소설·구매 INSERT 와 삭제 환급 UPDATE 는 새 칸을
넘기지 않아 NULL 이 되고 새 CHECK 를 모두 통과한다(숨김 NULL, 사유 NULL). 옛 코드의 다시 공개는 판 행을 쓰지 않는다(위 재실행이
메운다). 옛 코드의 "이미 산 화인가" 조회는 환급 여부를 보지 않고 첫 행을 집으므로, 환급 뒤 다시 산 행이 생겨도 오류는 없다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 새 표의 FK 가 `novels`·`novel_chapters`·`novel_chapter_revisions` 에, 칸·CHECK·
인덱스가 `novels`·`novel_purchases` 에 잠금을 거는데, 떠 있는 API 가 이 테이블들을 늘 읽고 쓰므로 오래 걸린 트랜잭션 뒤에서
기다리며 뒤의 요청을 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**downgrade**: 판 이력 표와 숨김·사유 칸을 지우고 옛 전체 유니크를 되살린다. 같은 화를 같은 사람이 환급 뒤 다시 산 행이
있으면 옛 유니크를 만들 수 없으므로 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다. 판 이력(산 때의 판)·숨김 표시·환급 사유를
잃는다 — 다시 올리면 판 이력은 그때 공개 중인 판으로만 채워지고, 숨긴 소설은 작가 목록에 다시 나타나며, 환급 사유는 모두
NULL(삭제로 읽힘)이 된다. 행이 있어도 멈추는 가드는 두지 않는다 — 테스트 스위트 끝의 `alembic downgrade base` 가 테스트가
커밋한 행 하나 때문에 깨지기 때문이다. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가
그대로 돈다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d77bce2bba4c"
down_revision: str | Sequence[str] | None = "0f82ea9f9fa5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

BACKFILL_CHAPTER_EDITIONS_SQL = """
INSERT INTO novel_chapter_editions (chapter_id, edition, novel_id, revision_id, title, author_note, published_at)
SELECT p.chapter_id, p.edition, p.novel_id, p.revision_id, p.title, p.author_note, p.published_at
FROM novel_chapter_publications p
ON CONFLICT (chapter_id, edition) DO NOTHING
"""

_REPURCHASED_SQL = """
SELECT count(*) FROM (
  SELECT 1 FROM novel_purchases
  WHERE buyer_user_id IS NOT NULL
  GROUP BY chapter_id, buyer_user_id
  HAVING count(*) > 1
) repurchased
"""


def backfill_chapter_editions(connection: sa.Connection) -> int:
    """판 행이 없는 화 공개본의 지금 판을 판 행으로 채우고, 채운 행 수를 돌려준다."""
    return connection.execute(sa.text(BACKFILL_CHAPTER_EDITIONS_SQL)).rowcount


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("novels", sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint("ck_novels_hidden_without_room", "novels", "hidden_at IS NULL OR chat_room_id IS NULL")

    op.add_column("novel_purchases", sa.Column("refund_reason", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_novel_purchases_refund_reason",
        "novel_purchases",
        "refund_reason IN ('deleted', 'publisher_withdrawn', 'novel_restricted', 'source_restricted', 'source_deleted')",
    )
    op.create_check_constraint(
        "ck_novel_purchases_refund_reason_after_refund",
        "novel_purchases",
        "refund_reason IS NULL OR refunded_at IS NOT NULL",
    )
    op.create_index(
        "ux_novel_purchases_unrefunded_chapter_buyer",
        "novel_purchases",
        ["chapter_id", "buyer_user_id"],
        unique=True,
        postgresql_where=sa.text("refunded_at IS NULL"),
    )
    op.drop_index("ux_novel_purchases_chapter_id_buyer_user_id", table_name="novel_purchases")

    op.create_table(
        "novel_chapter_editions",
        sa.Column("chapter_id", sa.Uuid(), nullable=False),
        sa.Column("edition", sa.Integer(), nullable=False),
        sa.Column("novel_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("author_note", sa.Text(), server_default="", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("edition >= 1", name="ck_novel_chapter_editions_edition_positive"),
        sa.ForeignKeyConstraint(["chapter_id"], ["novel_chapters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["novel_chapter_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chapter_id", "edition"),
    )
    op.create_index("ix_novel_chapter_editions_novel_id", "novel_chapter_editions", ["novel_id"], unique=False)
    op.create_index("ix_novel_chapter_editions_revision_id", "novel_chapter_editions", ["revision_id"], unique=False)

    filled = backfill_chapter_editions(op.get_bind())
    logger.warning("novel_chapter_editions: 화 공개본 %d개의 지금 판을 판 이력 첫 행으로 채웠다", filled)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    repurchased = op.get_bind().execute(sa.text(_REPURCHASED_SQL)).scalar_one()
    if repurchased:
        raise RuntimeError(
            f"환급 뒤 같은 화를 다시 산 구매자·화 {repurchased}쌍이 있어 옛 (화, 구매자) 전체 유니크를 만들 수 없다. 옛 코드로"
            " 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다)."
        )
    op.drop_index("ix_novel_chapter_editions_revision_id", table_name="novel_chapter_editions")
    op.drop_index("ix_novel_chapter_editions_novel_id", table_name="novel_chapter_editions")
    op.drop_table("novel_chapter_editions")

    op.create_index(
        "ux_novel_purchases_chapter_id_buyer_user_id", "novel_purchases", ["chapter_id", "buyer_user_id"], unique=True
    )
    op.drop_index("ux_novel_purchases_unrefunded_chapter_buyer", table_name="novel_purchases")
    op.drop_constraint("ck_novel_purchases_refund_reason_after_refund", "novel_purchases", type_="check")
    op.drop_constraint("ck_novel_purchases_refund_reason", "novel_purchases", type_="check")
    op.drop_column("novel_purchases", "refund_reason")

    op.drop_constraint("ck_novels_hidden_without_room", "novels", type_="check")
    op.drop_column("novels", "hidden_at")
