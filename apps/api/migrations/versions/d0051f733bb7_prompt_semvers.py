"""prompt semvers

Revision ID: d0051f733bb7
Revises: 495e9a75bb46
Create Date: 2026-10-24 18:00:00.000000

프롬프트 체인((레인, 모델) 세트 줄기)과 섹션(채널 하나, 또는 화자 라벨 넷 묶음 `speaker_labels`)에 `major.minor.patch` 판을
매길 표 둘을 더하고, 지금 체인마다 활성인 게시 세트 하나와 그 섹션 전부를 1.0.0 으로 매긴다.

- `prompt_set_semvers`: 게시 세트 하나 = 최대 한 행. 체인 안 번호 유니크(`ix_prompt_set_semvers_chain_semver`), 세트당 한 판
  (`ix_prompt_set_semvers_prompt_set_id`), 한 판은 다음 판의 기준이 한 번만 된다(`ix_prompt_set_semvers_base_set_id` — 같은
  기준판을 읽은 동시 게시 둘이 서로 다른 단계로 올려도 뒤 커밋을 막는다). CHECK 넷: 번호 범위, 단계 값, 단계와 기준판은 함께
  있거나 함께 없다, 자기 자신을 기준판으로 두지 않는다.
- `prompt_section_semvers`: (게시 세트, 섹션)마다 한 행. 번호 범위·단계 값 CHECK.
- 세트 FK 는 둘 다 `ON DELETE CASCADE`(판은 세트의 부속 기록이고, 체인을 통째로 지우는 코드와 옛 마이그레이션 downgrade 가 이
  표를 모른 채 세트를 지운다). 기준판 FK 는 CASCADE 가 아니다 — 다음 판의 기준이 된 세트를 지우면 판 사슬이 끊기므로 막는다.

**백필**: `legacy` 를 뺀 체인마다 활성 세트(어드민 목록의 활성 표시와 같은 순서 — `published_at` 최신, 같으면 id 큰 쪽) 하나를
1.0.0 으로, 그 세트의 채널마다와 화자 라벨 묶음을 1.0.0 으로 매긴다. 그 이전 게시본에는 판 행을 만들지 않는다(화면이 정수
번호로 "옛 판"으로 보여 준다). 기존 `prompt_sets`·`prompt_sections` 는 읽기만 한다 — 정수 `version` 과 섹션 내용을 대조하는
측정 도구가 그대로 맞는다.

**옛 이미지가 이 스키마 위에서 도는 구간**(배포 겹침, 이미지만 되돌린 동안): 옛 코드는 두 표를 모르고 읽지도 쓰지도 않는다.
기존 표에는 칸을 더하지 않아 옛 코드의 INSERT·SELECT 는 그대로다. 옛 코드가 게시한 세트는 판 행이 없을 뿐이고, 다음 새 코드
게시가 그 체인의 판이 가장 큰 세트와 견주므로 그 사이의 변경이 다음 판에 함께 셈해진다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다 — `prompt_sets` 를 가리키는 FK 를 만들 때 그 표에 `SHARE ROW EXCLUSIVE` 를 잠깐
잡는데, 이 잠금은 읽기와는 부딪치지 않고 옛 이미지 어드민의 초안 저장·게시(`prompt_sets` 쓰기)와 부딪친다. 그 쓰기 뒤에서 끝없이
기다리지 않고, 마이그레이션이 커밋될 때까지 그 쓰기를 오래 세우지 않게 5초 안에 못 잡으면 실패시킨다(다시 돌리면 된다).

**downgrade**: 단계(`level`)가 있는 체인 판(= 이 리비전 뒤 실제 게시로 매긴 판)이 하나라도 있으면 아무것도 바꾸기 전에
`RuntimeError` 로 멈춘다 — 판 이력을 조용히 지우지 않는다. 옛 이미지는 이 표를 읽지 않으므로 이미지만 되돌리는 데에는 downgrade
가 필요 없다. 없으면 두 표를 지우고, 다시 올리면 그때의 활성 세트가 다시 1.0.0 이 된다.

**앞으로의 문안 마이그레이션**: 게시 세트를 넣는 마이그레이션은 아래 `_assign_semver` 블록을 자기 파일에 그대로 복사해, 세트와
섹션을 넣은 직후(같은 체인의 다음 세트를 넣기 전에) 부른다. 마이그레이션은 `api.*` 와 서로를 import 하지 않으므로 블록은 그 리비전
시점의 규칙으로 얼어 있게 된다. 기본 단계는 어드민 게시와 같은 patch 이고, 슬롯을 더하는 마이그레이션(동작이 늘어남)은 그 채널에
minor 를 명시하고 고른 단계와 이유를 docstring 에 적는다. 번호를 매긴 게시본은 제자리에서 고치지 않는다 — 같은 (체인, 섹션,
번호)가 다른 내용을 가리키게 된다. 그런 마이그레이션의 downgrade 는 넣은 세트를 지우면 판 행도 CASCADE 로 지워지지만, 그 세트가
나중 게시의 기준판이 된 뒤라면 세트 삭제가 기준판 FK 에 막힌다 — 게시가 쌓인 뒤의 문안 downgrade 가 위험하다는 신호다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

import uuid
from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d0051f733bb7"
down_revision: str | Sequence[str] | None = "495e9a75bb46"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BACKFILL_SET_SEMVERS = sa.text(
    "INSERT INTO prompt_set_semvers (id, prompt_set_id, lane, model, major, minor, patch, level, base_set_id)"
    " SELECT gen_random_uuid(), a.id, a.lane, a.model, 1, 0, 0, NULL, NULL"
    " FROM ("
    "   SELECT DISTINCT ON (lane, model) id, lane, model"
    "   FROM prompt_sets"
    "   WHERE status = 'published'"
    "     AND lane IN ('story', 'character', 'publish_filter', 'novel', 'novel_screen')"
    "   ORDER BY lane, model, published_at DESC, id DESC"
    " ) a"
)

_BACKFILL_SECTION_SEMVERS = sa.text(
    "INSERT INTO prompt_section_semvers (id, prompt_set_id, channel, major, minor, patch, level)"
    " SELECT gen_random_uuid(), s.prompt_set_id, s.channel, 1, 0, 0, NULL"
    " FROM (SELECT DISTINCT p.prompt_set_id, p.channel"
    "       FROM prompt_sections p JOIN prompt_set_semvers v ON v.prompt_set_id = p.prompt_set_id) s"
    " UNION ALL"
    " SELECT gen_random_uuid(), v.prompt_set_id, 'speaker_labels', 1, 0, 0, NULL FROM prompt_set_semvers v"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "prompt_set_semvers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_set_id", sa.Uuid(), nullable=False),
        sa.Column("lane", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("major", sa.Integer(), nullable=False),
        sa.Column("minor", sa.Integer(), nullable=False),
        sa.Column("patch", sa.Integer(), nullable=False),
        sa.Column("level", sa.Text(), nullable=True),
        sa.Column("base_set_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("major >= 1 AND minor >= 0 AND patch >= 0", name="ck_prompt_set_semvers_parts_range"),
        sa.CheckConstraint(
            "level IS NULL OR level IN ('major', 'minor', 'patch')", name="ck_prompt_set_semvers_level_values"
        ),
        sa.CheckConstraint("(level IS NULL) = (base_set_id IS NULL)", name="ck_prompt_set_semvers_level_iff_base"),
        sa.CheckConstraint(
            "base_set_id IS NULL OR base_set_id <> prompt_set_id", name="ck_prompt_set_semvers_not_own_base"
        ),
        sa.ForeignKeyConstraint(["prompt_set_id"], ["prompt_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["base_set_id"], ["prompt_sets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prompt_set_semvers_prompt_set_id", "prompt_set_semvers", ["prompt_set_id"], unique=True)
    op.create_index(
        "ix_prompt_set_semvers_chain_semver",
        "prompt_set_semvers",
        ["lane", "model", "major", "minor", "patch"],
        unique=True,
    )
    op.create_index("ix_prompt_set_semvers_base_set_id", "prompt_set_semvers", ["base_set_id"], unique=True)

    op.create_table(
        "prompt_section_semvers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_set_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("major", sa.Integer(), nullable=False),
        sa.Column("minor", sa.Integer(), nullable=False),
        sa.Column("patch", sa.Integer(), nullable=False),
        sa.Column("level", sa.Text(), nullable=True),
        sa.CheckConstraint("major >= 1 AND minor >= 0 AND patch >= 0", name="ck_prompt_section_semvers_parts_range"),
        sa.CheckConstraint(
            "level IS NULL OR level IN ('major', 'minor', 'patch')", name="ck_prompt_section_semvers_level_values"
        ),
        sa.ForeignKeyConstraint(["prompt_set_id"], ["prompt_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prompt_section_semvers_set_channel", "prompt_section_semvers", ["prompt_set_id", "channel"], unique=True
    )

    bind = op.get_bind()
    bind.execute(_BACKFILL_SET_SEMVERS)
    bind.execute(_BACKFILL_SECTION_SEMVERS)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    assigned = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM prompt_set_semvers WHERE level IS NOT NULL"))
        .scalar_one()
    )
    if assigned:
        raise RuntimeError(
            f"게시로 매긴 프롬프트 판 {assigned}행이 남아 있다 — 판 이력을 지우지 않는다. 옛 이미지는 이 표를 읽지 않으므로"
            " 이미지만 되돌린다."
        )
    op.drop_index("ix_prompt_section_semvers_set_channel", table_name="prompt_section_semvers")
    op.drop_table("prompt_section_semvers")
    op.drop_index("ix_prompt_set_semvers_base_set_id", table_name="prompt_set_semvers")
    op.drop_index("ix_prompt_set_semvers_chain_semver", table_name="prompt_set_semvers")
    op.drop_index("ix_prompt_set_semvers_prompt_set_id", table_name="prompt_set_semvers")
    op.drop_table("prompt_set_semvers")


# ---- 문안 마이그레이션이 복사해 쓰는 판 매기기 블록 ---------------------------------------------------------
#
# 이 리비전의 upgrade 는 부르지 않는다(백필은 위 SQL 이 한다). 앞으로 게시 세트를 넣는 마이그레이션이 이 블록을 그대로 복사한다.
# 어드민 게시(`api/admin/prompt_semver.py`)와 같은 규칙이다 — 체인에서 판이 가장 큰 세트(기준판)와 섹션 내용을 바이트로 견주어
# 바뀐 섹션만 고른 단계로 올리고, 체인은 그중 가장 큰 단계로 올린다. 바뀐 섹션의 새 번호는 그 체인에서 그 섹션이 가졌던 가장 큰
# 번호에서 올린다(빠졌다가 다시 들어온 섹션이 옛 번호를 다른 내용으로 다시 쓰지 않게). 기준판이 없으면 체인·섹션 전부 1.0.0 이고
# 단계는 무시한다.

_SPEAKER_LABELS = "speaker_labels"
_LEVEL_RANK = {"patch": 0, "minor": 1, "major": 2}


def _bump(number: tuple[int, int, int], level: str) -> tuple[int, int, int]:
    major, minor, patch = number
    if level == "major":
        return (major + 1, 0, 0)
    if level == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def _section_contents(conn: Connection, set_id: uuid.UUID) -> dict[str, tuple[object, ...]]:
    labels = conn.execute(
        sa.text(
            "SELECT user_label, story_assistant_label, story_example_label, character_assistant_label"
            " FROM prompt_sets WHERE id = :id"
        ),
        {"id": set_id},
    ).one()
    rows: dict[str, list[tuple[str, str, str, str, bool, int]]] = {}
    for channel, scope, slot, variant, body, conditional, order in conn.execute(
        sa.text(
            'SELECT channel, scope, slot, variant, body, conditional, "order" FROM prompt_sections'
            " WHERE prompt_set_id = :id"
        ),
        {"id": set_id},
    ):
        rows.setdefault(channel, []).append((scope, slot, variant, body, conditional, order))
    contents: dict[str, tuple[object, ...]] = {channel: tuple(sorted(items)) for channel, items in rows.items()}
    contents[_SPEAKER_LABELS] = tuple(labels)
    return contents


def _assign_semver(
    conn: Connection, *, set_id: uuid.UUID, levels: Mapping[str, str] | None = None, default_level: str = "patch"
) -> None:
    """방금 넣은 게시 세트 `set_id` 에 체인·섹션 판을 매긴다. `levels` 는 바뀐 섹션마다 고른 단계이고, 고르지 않은 바뀐 섹션은
    `default_level` 이다. 바뀌지 않은 섹션 이름을 `levels` 에 넣으면 작성 실수라 업그레이드 때 바로 드러나게 멈춘다."""
    lane, model = conn.execute(sa.text("SELECT lane, model FROM prompt_sets WHERE id = :id"), {"id": set_id}).one()
    contents = _section_contents(conn, set_id)
    picked_levels = dict(levels or {})
    base = conn.execute(
        sa.text(
            "SELECT prompt_set_id, major, minor, patch FROM prompt_set_semvers WHERE lane = :lane AND model = :model"
            " ORDER BY major DESC, minor DESC, patch DESC LIMIT 1"
        ),
        {"lane": lane, "model": model},
    ).first()

    section_rows: dict[str, tuple[tuple[int, int, int], str | None]] = {}
    if base is None:
        unknown = sorted(set(picked_levels) - set(contents))
        if unknown:
            raise RuntimeError(f"판 단계를 고른 섹션이 이 세트에 없다: {unknown}")
        chain_number, chain_level, base_set_id = (1, 0, 0), None, None
        section_rows = {channel: ((1, 0, 0), None) for channel in contents}
    else:
        base_set_id = base.prompt_set_id
        base_numbers = {
            channel: (major, minor, patch)
            for channel, major, minor, patch in conn.execute(
                sa.text(
                    "SELECT channel, major, minor, patch FROM prompt_section_semvers WHERE prompt_set_id = :id"
                ),
                {"id": base_set_id},
            )
        }
        # 판 행 없이 내용만 있는 기준판 섹션은 물려줄 번호가 없어 기준판에 없던 섹션으로 본다(새로 들어온 섹션처럼 이어 올림).
        base_contents = {
            channel: content
            for channel, content in _section_contents(conn, base_set_id).items()
            if channel in base_numbers
        }
        chain_max = {
            channel: (major, minor, patch)
            for channel, major, minor, patch in conn.execute(
                sa.text(
                    "SELECT DISTINCT ON (s.channel) s.channel, s.major, s.minor, s.patch"
                    " FROM prompt_section_semvers s JOIN prompt_set_semvers v ON v.prompt_set_id = s.prompt_set_id"
                    " WHERE v.lane = :lane AND v.model = :model"
                    " ORDER BY s.channel, s.major DESC, s.minor DESC, s.patch DESC"
                ),
                {"lane": lane, "model": model},
            )
        }
        changed = {
            channel
            for channel in set(contents) | set(base_contents)
            if contents.get(channel) != base_contents.get(channel)
        }
        not_changed = sorted(set(picked_levels) - changed)
        if not_changed:
            raise RuntimeError(f"바뀌지 않은 섹션에 판 단계를 골랐다: {not_changed}")
        chosen = {channel: picked_levels.get(channel, default_level) for channel in changed}
        chain_level = max(chosen.values(), key=_LEVEL_RANK.__getitem__, default="patch")
        chain_number = _bump((base.major, base.minor, base.patch), chain_level)
        for channel in contents:
            if channel not in changed:
                section_rows[channel] = (base_numbers[channel], None)
            elif channel in chain_max:
                section_rows[channel] = (_bump(chain_max[channel], chosen[channel]), chosen[channel])
            else:
                section_rows[channel] = ((1, 0, 0), chosen[channel])

    conn.execute(
        sa.text(
            "INSERT INTO prompt_set_semvers"
            " (id, prompt_set_id, lane, model, major, minor, patch, level, base_set_id)"
            " VALUES (:id, :set_id, :lane, :model, :major, :minor, :patch, :level, :base_set_id)"
        ),
        {
            "id": uuid.uuid4(),
            "set_id": set_id,
            "lane": lane,
            "model": model,
            "major": chain_number[0],
            "minor": chain_number[1],
            "patch": chain_number[2],
            "level": chain_level,
            "base_set_id": base_set_id,
        },
    )
    for channel, ((major, minor, patch), level) in section_rows.items():
        conn.execute(
            sa.text(
                "INSERT INTO prompt_section_semvers (id, prompt_set_id, channel, major, minor, patch, level)"
                " VALUES (:id, :set_id, :channel, :major, :minor, :patch, :level)"
            ),
            {
                "id": uuid.uuid4(),
                "set_id": set_id,
                "channel": channel,
                "major": major,
                "minor": minor,
                "patch": patch,
                "level": level,
            },
        )
