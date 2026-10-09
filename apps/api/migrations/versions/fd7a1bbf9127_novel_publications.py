"""novel publications

Revision ID: fd7a1bbf9127
Revises: fb754d605e96
Create Date: 2026-10-09 17:57:22.310355

노벨(공개 소설)의 뼈대 테이블 셋을 만든다.

- `novel_publications`: 소설 한 권의 공개 상태(게시자가 정하는 공개 범위·운영자가 정하는 이용제한 두 축)와 공개 시점의 소설
  제목·소개 사본.
- `novel_chapter_publications`: 화마다 공개 시점에 얼린 개정과 화 제목·작가의 말 사본, 판 번호.
- `novel_screenings`: 공개 전 텍스트 심사 한 번의 판정(통과·거부, 짚은 자리, 심사 모델이 쓴 사유).

세 테이블 모두 소설·화·개정 FK 가 `ON DELETE CASCADE` 다. 이미지만 옛 판으로 되돌렸을 때 옛 코드의 소설 삭제·마지막 묶음
삭제·탈퇴는 이 테이블들을 모르고 개정 → 화 → 소설 순으로 지우는데, cascade 가 없으면 그 DELETE 가 FK 위반으로 500 이 된다.
새 코드는 cascade 에 기대지 않고 `novelize/deletion.py` 에서 직접 지운다. 상태 칸은 Text + CHECK 이고(네이티브 enum 에 값을
더하면 그 값을 모르는 옛 코드의 조회가 500 이 된다), CHECK 는 `alembic check` 가 비교하지 않아 행위 테스트가 유일한 검증이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 새 테이블이 `novels`·`novel_chapters`·`novel_chapter_revisions`·`users` 에
FK 를 걸 때 그 테이블에 짧은 `SHARE ROW EXCLUSIVE` 가 잡히는데, 떠 있는 API 가 그 테이블들을 늘 쓰므로 오래 걸린 트랜잭션
뒤에서 기다리며 뒤의 쓰기를 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(체인 전체 롤백, 다시 돌리면 된다).

**배포 겹침** — 옛 코드는 세 테이블을 모르고 읽지도 쓰지도 않는다. 옛 코드의 소설·화 삭제는 위 cascade 로 이 행들까지 지운다.

**downgrade** — 공개 상태 테이블에 행이 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다. 지우면 공개 중인
소설이 말없이 내려가고, 다시 올려도 돌아오지 않는다. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(이
스키마에서 옛 코드가 그대로 돈다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision: str = "fd7a1bbf9127"
down_revision: str | Sequence[str] | None = "fb754d605e96"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_downgradable(conn: Connection) -> None:
    for table in ("novel_publications", "novel_chapter_publications"):
        count = conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        if count:
            raise RuntimeError(
                f"{table} 에 {count}행이 있다 — 지우면 공개 중인 소설이 말없이 내려간다. 옛 코드로 돌아가기만 하려면"
                " downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다)."
            )


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 소설 쓰기가 FK 생성의 락 대기 뒤로 줄서지 않게 — 위 docstring.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "novel_publications",
        sa.Column("novel_id", sa.Uuid(), nullable=False),
        sa.Column("visibility", sa.Text(), nullable=False),
        sa.Column("moderation_status", sa.Text(), server_default="normal", nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("synopsis", sa.Text(), server_default="", nullable=False),
        sa.Column("first_published_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "moderation_status IN ('normal', 'restricted')", name="ck_novel_publications_moderation_status"
        ),
        sa.CheckConstraint("visibility IN ('public', 'withdrawn')", name="ck_novel_publications_visibility"),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("novel_id"),
    )
    op.create_table(
        "novel_screenings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("novel_id", sa.Uuid(), nullable=False),
        sa.Column("chapter_id", sa.Uuid(), nullable=True),
        sa.Column("chapter_ordinal", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("flagged_parts", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "flagged_parts <@ ARRAY['novel_title', 'synopsis', 'chapter_title', 'author_note', 'chapter_body']::text[]",
            name="ck_novel_screenings_flagged_parts",
        ),
        sa.CheckConstraint(
            "outcome = 'rejected' OR flagged_parts = '{}'", name="ck_novel_screenings_passed_flags_none"
        ),
        sa.CheckConstraint("outcome IN ('passed', 'rejected')", name="ck_novel_screenings_outcome"),
        sa.ForeignKeyConstraint(["chapter_id"], ["novel_chapters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_novel_screenings_chapter_id", "novel_screenings", ["chapter_id"], unique=False)
    op.create_index(
        "ix_novel_screenings_novel_id_created_at",
        "novel_screenings",
        ["novel_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "novel_chapter_publications",
        sa.Column("chapter_id", sa.Uuid(), nullable=False),
        sa.Column("novel_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("author_note", sa.Text(), server_default="", nullable=False),
        sa.Column("edition", sa.Integer(), server_default="1", nullable=False),
        sa.Column("first_published_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("edition >= 1", name="ck_novel_chapter_publications_edition_positive"),
        sa.CheckConstraint("ordinal >= 1", name="ck_novel_chapter_publications_ordinal_positive"),
        sa.ForeignKeyConstraint(["chapter_id"], ["novel_chapters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["novel_chapter_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chapter_id"),
    )
    op.create_index(
        "ix_novel_chapter_publications_revision_id", "novel_chapter_publications", ["revision_id"], unique=False
    )
    op.create_index(
        "ux_novel_chapter_publications_novel_id_ordinal",
        "novel_chapter_publications",
        ["novel_id", "ordinal"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    _assert_downgradable(op.get_bind())
    op.drop_index("ux_novel_chapter_publications_novel_id_ordinal", table_name="novel_chapter_publications")
    op.drop_index("ix_novel_chapter_publications_revision_id", table_name="novel_chapter_publications")
    op.drop_table("novel_chapter_publications")
    op.drop_index("ix_novel_screenings_novel_id_created_at", table_name="novel_screenings")
    op.drop_index("ix_novel_screenings_chapter_id", table_name="novel_screenings")
    op.drop_table("novel_screenings")
    op.drop_table("novel_publications")
