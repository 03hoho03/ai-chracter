"""novel chapter illustrations

Revision ID: b871b88d2a90
Revises: 211f81f33be5
Create Date: 2026-10-22 18:00:00.000000

소설 화에 삽화를 붙이는 데 필요한 스키마를 한 번에 더한다.

- `novel_chapter_illustrations`: 화 개정 하나에 붙은 삽화 한 장(앵커 문단 블록 id·앞/뒤·같은 자리 안 순서·그림 자산·출처).
  앵커와 앞/뒤가 둘 다 비면 "위치 확인 필요" 행이다. 개정 FK 는 `ON DELETE CASCADE` — 이 표를 모르는 옛 코드의 개정 삭제(소설
  삭제·묶음 삭제·탈퇴 정리)가 FK 위반이 되지 않게. 그림 FK 는 기본(지우기 거부)이다.
- 화 개정 출처 CHECK 에 `illustration`(배치만 바꾼 개정) 추가.
- 심사 거부 기록의 자리 CHECK 에 `illustration`(화의 삽화) 추가.
- `novel_chapter_publications`·`novel_chapter_editions` 에 `illustrations_screened_at`(TIMESTAMPTZ NULL): 그 공개본·판이 얼린
  개정의 삽화를 심사했는가. 비어 있으면 독자 화면에 그림을 싣지 않는다.
- `novel_illustration_screen_passes`: 삽화 심사 통과 기억(그림 바이트 sha256·모델·심사 문안 판이 키).
- `novel_illustration_takedowns`: 운영자가 모든 판에서 내린 그림(바이트 sha256 이 키).

**옛 이미지가 이 스키마 위에서 도는 구간**: 옛 코드는 새 표 셋을 모르고, 넓힌 CHECK 둘은 옛 값을 그대로 받으며, 새 칸 둘은
NULL 로 채워진다. 개정을 지우는 옛 경로는 배치 행을 CASCADE 로 함께 지운다. 옛 코드의 생성 이미지 삭제·탈퇴는 배치를 사용처로
보지 않아 배치가 쓰는 그림을 지우려다 FK 거부로 실패하지만, 배치는 삽화 스위치를 켠 뒤에만 생기므로 겹침 동안 0행이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다 — 떠 있는 API 가 늘 읽고 쓰는 표(개정·심사 기록·공개본·판)의 ALTER 라, 오래 걸린
트랜잭션 뒤에서 기다리며 뒤의 요청을 줄 세우지 않게 5초 안에 잠금을 못 잡으면 실패시킨다(다시 돌리면 된다). CHECK 를 넓히는
것은 모든 기존 행이 통과하는 바꿈이고 새 칸은 NULL 이라 표를 다시 쓰지 않는다.

**downgrade**: 옛 스키마가 받을 수 없는 행(출처 `illustration` 개정·`illustration` 자리 거부 기록·배치 행·삽화 심사 시각이 찬
공개본·판·통과 기억·내림 기록)이 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다 — 조용히 지우면 작가의 삽화와
운영 기록이 사라진다. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(옛 코드는 이 스키마에서 그대로 돈다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b871b88d2a90"
down_revision: str | Sequence[str] | None = "211f81f33be5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_REVISION_SOURCE_CHECK = "source IN ('generate', 'regenerate', 'manual_edit', 'ai_edit', 'revert')"
_NEW_REVISION_SOURCE_CHECK = "source IN ('generate', 'regenerate', 'manual_edit', 'ai_edit', 'revert', 'illustration')"
_OLD_FLAGGED_PARTS_CHECK = (
    "flagged_parts <@ ARRAY['novel_title', 'synopsis', 'chapter_title', 'author_note', 'chapter_body',"
    " 'change_summary']::text[]"
)
_NEW_FLAGGED_PARTS_CHECK = (
    "flagged_parts <@ ARRAY['novel_title', 'synopsis', 'chapter_title', 'author_note', 'chapter_body',"
    " 'change_summary', 'illustration']::text[]"
)

# 옛 스키마가 받을 수 없는 행. 종류 → 그 행을 세는 SQL.
_DOWNGRADE_BLOCKERS = {
    "출처 illustration 개정": "SELECT count(*) FROM novel_chapter_revisions WHERE source = 'illustration'",
    "illustration 자리 거부 기록": "SELECT count(*) FROM novel_screenings WHERE 'illustration' = ANY(flagged_parts)",
    "배치 행": "SELECT count(*) FROM novel_chapter_illustrations",
    "삽화를 심사한 공개본": "SELECT count(*) FROM novel_chapter_publications WHERE illustrations_screened_at IS NOT NULL",
    "삽화를 심사한 판": "SELECT count(*) FROM novel_chapter_editions WHERE illustrations_screened_at IS NOT NULL",
    "삽화 심사 통과 기억": "SELECT count(*) FROM novel_illustration_screen_passes",
    "삽화 내림 기록": "SELECT count(*) FROM novel_illustration_takedowns",
}


def downgrade_blockers(conn: Connection) -> dict[str, int]:
    """downgrade 를 막는 행을 종류별로 센다(0 인 종류는 뺀다)."""
    counts = {label: conn.execute(sa.text(sql)).scalar_one() for label, sql in _DOWNGRADE_BLOCKERS.items()}
    return {label: count for label, count in counts.items() if count}


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "novel_chapter_illustrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("anchor_block_id", sa.Uuid(), nullable=True),
        sa.Column("placement", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("placement IN ('before', 'after')", name="ck_novel_chapter_illustrations_placement"),
        sa.CheckConstraint(
            "source IN ('upload', 'original', 'generated')", name="ck_novel_chapter_illustrations_source"
        ),
        sa.CheckConstraint(
            "(anchor_block_id IS NULL) = (placement IS NULL)", name="ck_novel_chapter_illustrations_anchor_pair"
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_novel_chapter_illustrations_sort_order_nonnegative"),
        sa.ForeignKeyConstraint(["revision_id"], ["novel_chapter_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_novel_chapter_illustrations_slot",
        "novel_chapter_illustrations",
        ["revision_id", "anchor_block_id", "placement", "sort_order"],
        unique=True,
        postgresql_where=sa.text("anchor_block_id IS NOT NULL"),
    )
    op.create_index(
        "ix_novel_chapter_illustrations_revision_id", "novel_chapter_illustrations", ["revision_id"], unique=False
    )
    op.create_index("ix_novel_chapter_illustrations_asset_id", "novel_chapter_illustrations", ["asset_id"], unique=False)

    op.drop_constraint("ck_novel_chapter_revisions_source", "novel_chapter_revisions", type_="check")
    op.create_check_constraint("ck_novel_chapter_revisions_source", "novel_chapter_revisions", _NEW_REVISION_SOURCE_CHECK)
    op.drop_constraint("ck_novel_screenings_flagged_parts", "novel_screenings", type_="check")
    op.create_check_constraint("ck_novel_screenings_flagged_parts", "novel_screenings", _NEW_FLAGGED_PARTS_CHECK)

    op.add_column(
        "novel_chapter_publications", sa.Column("illustrations_screened_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "novel_chapter_editions", sa.Column("illustrations_screened_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "novel_illustration_screen_passes",
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("passed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("content_sha256", "model", "prompt_version"),
    )
    op.create_table(
        "novel_illustration_takedowns",
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("content_sha256"),
    )
    op.create_index(
        "ix_novel_illustration_takedowns_asset_id", "novel_illustration_takedowns", ["asset_id"], unique=False
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    blockers = downgrade_blockers(op.get_bind())
    if blockers:
        found = ", ".join(f"{label} {count}행" for label, count in blockers.items())
        raise RuntimeError(
            f"옛 스키마가 받을 수 없는 삽화 행이 있다: {found}. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다"
            "(이 스키마에서 옛 코드가 그대로 돈다). 꼭 내려야 하면 삽화 스위치를 끄고 그 행들을 기록으로 남긴 뒤 정리하고 다시 돌린다."
        )
    op.drop_index("ix_novel_illustration_takedowns_asset_id", table_name="novel_illustration_takedowns")
    op.drop_table("novel_illustration_takedowns")
    op.drop_table("novel_illustration_screen_passes")
    op.drop_column("novel_chapter_editions", "illustrations_screened_at")
    op.drop_column("novel_chapter_publications", "illustrations_screened_at")
    op.drop_constraint("ck_novel_screenings_flagged_parts", "novel_screenings", type_="check")
    op.create_check_constraint("ck_novel_screenings_flagged_parts", "novel_screenings", _OLD_FLAGGED_PARTS_CHECK)
    op.drop_constraint("ck_novel_chapter_revisions_source", "novel_chapter_revisions", type_="check")
    op.create_check_constraint("ck_novel_chapter_revisions_source", "novel_chapter_revisions", _OLD_REVISION_SOURCE_CHECK)
    op.drop_index("ix_novel_chapter_illustrations_asset_id", table_name="novel_chapter_illustrations")
    op.drop_index("ix_novel_chapter_illustrations_revision_id", table_name="novel_chapter_illustrations")
    op.drop_index("ux_novel_chapter_illustrations_slot", table_name="novel_chapter_illustrations")
    op.drop_table("novel_chapter_illustrations")
