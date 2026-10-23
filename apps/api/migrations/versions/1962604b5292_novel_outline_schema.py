"""novel outline schema

Revision ID: 1962604b5292
Revises: 7738b72179c8
Create Date: 2026-10-23 17:00:00.000000

구성 흐름(구간 선택 → 전체 구성안 → 화별 장면 구성안 → 원고)이 쓸 스키마를 더한다. 이 리비전만으로는 행을 쓰는 코드가 없다.

- `novel_jobs.kind` 의 CHECK(`ck_novel_jobs_kind`)를 작업 셋(`outline_generate`·`episode_outline_generate`·
  `outline_chapter_generate`)을 더한 목록으로 바꾼다(DROP → ADD). 넓히기만이라 옛 값은 그대로 통과한다.
- `novel_jobs` 에 nullable 칸 셋(`outline_id`·`outline_episode_key`·`episode_outline_id`, FK 없음)과 그 칸을 구성 흐름 작업에만
  요구하는 CHECK(`ck_novel_jobs_outline_target`), 원고의 하루 상한 집계용 부분 인덱스.
- `novel_chapters.episode_outline_id`(nullable, FK 없음)와 부분 인덱스 — 구성 흐름 원고가 쓴 화의 근거 장면 구성안.
- 표 `novel_outlines`(전체 구성안 리비전)·`novel_episode_outlines`(화별 장면 구성안 리비전)·`novel_scene_blocks`(블록 id → 장면).
  소설·화·구성안을 가리키는 FK 는 모두 `ON DELETE CASCADE`. 남는 표(화·작업)가 이 표들을 가리키는 칸에는 FK 가 없다 — 판매된
  소설을 숨겨 남길 때 작가 전용인 구성안은 지우고 화·작업 행은 남기기 때문이다.

**옛 이미지가 이 스키마 위에서 도는 구간**(배포 겹침, 이미지만 되돌린 동안): 옛 코드는 새 칸·표를 모르고 읽지도 쓰지도 않는다.
옛 코드의 작업·화 INSERT 는 새 칸을 비워 두고, 새 CHECK 는 새 작업 종류에만 걸려 옛 값은 통과한다. 옛 코드의 소설 삭제·탈퇴·
마지막 묶음 삭제는 소설·화 행을 지울 때 새 표의 행을 CASCADE 로 함께 지운다. 옛 코드가 새 작업 종류 행을 응답으로 내면
응답 검증이 500 이 되는데(진행 중 작업과 그 작업 id 조회), 이 리비전만으로는 그 행을 쓰는 코드가 없다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다 — 떠 있는 API 가 늘 쓰는 `novel_jobs`·`novel_chapters` 를 ALTER 하므로, 오래 걸린
트랜잭션 뒤에서 기다리며 뒤의 요청을 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(다시 돌리면 된다). 두 표는 작아 CHECK 검증이
짧다.

**downgrade**: 새 작업 종류의 작업 행이나 구성안·장면 구성안·장면 블록 행이 하나라도 있으면 아무것도 바꾸기 전에
`RuntimeError` 로 멈춘다 — 값을 치른 산출물과 그 차감 기록이라 조용히 지우지 않고, 좁힌 CHECK 를 다시 걸 수도 없다. 옛 이미지는
이 스키마 위에서도 돌므로 이미지만 되돌리는 데에는 downgrade 가 필요 없다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1962604b5292"
down_revision: str | Sequence[str] | None = "7738b72179c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_KINDS = "'chapter_generate', 'chapter_regenerate', 'ai_edit', 'chain_generate'"
_NEW_KINDS = (
    "'chapter_generate', 'chapter_regenerate', 'ai_edit', 'chain_generate', 'outline_generate',"
    " 'episode_outline_generate', 'outline_chapter_generate'"
)
_OUTLINE_KINDS = "'outline_generate', 'episode_outline_generate', 'outline_chapter_generate'"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint("ck_novel_jobs_kind", "novel_jobs", type_="check")
    op.create_check_constraint("ck_novel_jobs_kind", "novel_jobs", f"kind IN ({_NEW_KINDS})")
    op.add_column("novel_jobs", sa.Column("outline_id", sa.Uuid(), nullable=True))
    op.add_column("novel_jobs", sa.Column("outline_episode_key", sa.Uuid(), nullable=True))
    op.add_column("novel_jobs", sa.Column("episode_outline_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        "ck_novel_jobs_outline_target",
        "novel_jobs",
        "(kind <> 'episode_outline_generate' OR (outline_id IS NOT NULL AND outline_episode_key IS NOT NULL))"
        " AND (kind <> 'outline_chapter_generate'"
        " OR (episode_outline_id IS NOT NULL AND outline_episode_key IS NOT NULL))",
    )
    op.create_index(
        "ix_novel_jobs_episode_outline_id_created_at",
        "novel_jobs",
        ["episode_outline_id", "created_at"],
        postgresql_where=sa.text("episode_outline_id IS NOT NULL"),
    )
    op.add_column("novel_chapters", sa.Column("episode_outline_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_novel_chapters_episode_outline_id",
        "novel_chapters",
        ["episode_outline_id"],
        postgresql_where=sa.text("episode_outline_id IS NOT NULL"),
    )

    op.create_table(
        "novel_outlines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("novel_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("selection_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("episodes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_novel_outlines_revision_positive"),
        sa.CheckConstraint("source IN ('generate', 'edit')", name="ck_novel_outlines_source"),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ux_novel_outlines_novel_id_revision", "novel_outlines", ["novel_id", "revision"], unique=True)

    op.create_table(
        "novel_episode_outlines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("novel_id", sa.Uuid(), nullable=False),
        sa.Column("outline_id", sa.Uuid(), nullable=False),
        sa.Column("episode_key", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("scenes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_novel_episode_outlines_revision_positive"),
        sa.CheckConstraint("source IN ('generate', 'edit')", name="ck_novel_episode_outlines_source"),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outline_id"], ["novel_outlines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_novel_episode_outlines_novel_id_episode_key_revision",
        "novel_episode_outlines",
        ["novel_id", "episode_key", "revision"],
        unique=True,
    )
    op.create_index("ix_novel_episode_outlines_outline_id", "novel_episode_outlines", ["outline_id"])

    op.create_table(
        "novel_scene_blocks",
        sa.Column("block_id", sa.Uuid(), nullable=False),
        sa.Column("chapter_id", sa.Uuid(), nullable=False),
        sa.Column("episode_outline_id", sa.Uuid(), nullable=False),
        sa.Column("scene_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["chapter_id"], ["novel_chapters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["episode_outline_id"], ["novel_episode_outlines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("block_id"),
    )
    op.create_index("ix_novel_scene_blocks_chapter_id", "novel_scene_blocks", ["chapter_id"])
    op.create_index("ix_novel_scene_blocks_episode_outline_id", "novel_scene_blocks", ["episode_outline_id"])


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    bind = op.get_bind()
    counts = {
        "구성 흐름 작업": bind.execute(
            sa.text(f"SELECT count(*) FROM novel_jobs WHERE kind IN ({_OUTLINE_KINDS})")
        ).scalar_one(),
        "전체 구성안": bind.execute(sa.text("SELECT count(*) FROM novel_outlines")).scalar_one(),
        "장면 구성안": bind.execute(sa.text("SELECT count(*) FROM novel_episode_outlines")).scalar_one(),
        "장면 블록": bind.execute(sa.text("SELECT count(*) FROM novel_scene_blocks")).scalar_one(),
    }
    left = [f"{name} {count}행" for name, count in counts.items() if count]
    if left:
        raise RuntimeError(
            f"{', '.join(left)}이 남아 있다 — 값을 치른 구성안·원고와 그 차감 기록이라 지우지 않고, 좁힌 작업 종류 CHECK 도 다시"
            " 걸 수 없다. 옛 이미지는 이 스키마가 있어도 돌므로 이미지만 되돌린다."
        )
    op.drop_index("ix_novel_scene_blocks_episode_outline_id", table_name="novel_scene_blocks")
    op.drop_index("ix_novel_scene_blocks_chapter_id", table_name="novel_scene_blocks")
    op.drop_table("novel_scene_blocks")
    op.drop_index("ix_novel_episode_outlines_outline_id", table_name="novel_episode_outlines")
    op.drop_index("ux_novel_episode_outlines_novel_id_episode_key_revision", table_name="novel_episode_outlines")
    op.drop_table("novel_episode_outlines")
    op.drop_index("ux_novel_outlines_novel_id_revision", table_name="novel_outlines")
    op.drop_table("novel_outlines")
    op.drop_index("ix_novel_chapters_episode_outline_id", table_name="novel_chapters")
    op.drop_column("novel_chapters", "episode_outline_id")
    op.drop_index("ix_novel_jobs_episode_outline_id_created_at", table_name="novel_jobs")
    op.drop_constraint("ck_novel_jobs_outline_target", "novel_jobs", type_="check")
    op.drop_column("novel_jobs", "episode_outline_id")
    op.drop_column("novel_jobs", "outline_episode_key")
    op.drop_column("novel_jobs", "outline_id")
    op.drop_constraint("ck_novel_jobs_kind", "novel_jobs", type_="check")
    op.create_check_constraint("ck_novel_jobs_kind", "novel_jobs", f"kind IN ({_OLD_KINDS})")
