"""haiku writer prompt chains

Revision ID: 45e57ce4d815
Revises: 02a8ea9563a1
Create Date: 2026-10-30 12:00:00.000000

채팅 글쓰기 모델 `haiku_writer`(Claude Haiku 5.5)의 프롬프트 체인 둘(story·character)을 심는다. 어드민으로는 만들 수 없다 — 복제는
같은 체인 안에서만이고, 활성 세트가 없는 빈 체인은 초안 조회부터 실패한다. 이 체인이 없으면 Haiku 방의 첫 턴이 차감 뒤 활성 세트를
못 찾아 환불로 끝나므로, 모델을 채팅에 노출하기 전에 이 리비전이 배포에 실려 있어야 한다.

**심는 것**: 레인마다 그 레인 **Sonnet 활성 세트의 바이트 사본** 하나 — 라벨 넷과 모든 채널 행(본문·scope·variant·conditional·
order 그대로). Claude 계열 생성 문안이고 같은 시기에 열어 재는 가장 가까운 모델이라 원본으로 고른다(Gemini 원본은 Claude 체인의
손질을 잃는다). 판정·요약 채널은 Haiku 방에서 읽히지 않지만(판정은 판정 전용 `haiku` 체인이 맡는다) Claude 세트의 게시 검증이
그 채널을 요구해 함께 복사한다. 초안은 심지 않는다 — 초안 조회는 초안이 없으면 활성 세트 사본을 돌려준다.

**PK·버전**: 세트 id 는 리터럴(`NEW_SET_IDS`), 섹션 id 는 새 namespace 의 `uuid5("{lane}:haiku_writer:{channel}:{scope}:{slot}:{variant}")`.
`version` 은 전 레인·전 모델 published 최대 + 1 을 story·character 순서로(어드민 게시와 같은 규칙). 판(semver)은 세트마다 넣은
직후 아래 `_assign_semver` 블록(판 표 리비전 `d0051f733bb7` 에서 그대로 복사)으로 매긴다 — 새 체인의 첫 판이라 1.0.0 이다.

**`published_at` = 그 레인 Gemini 활성 − 1초.** 이 체인에는 세트가 하나뿐이라 모델로 거르는 활성 조회는 늘 이 세트를 고르고,
모델 열을 모르는 레인만 보는 옛 조회(옛 이미지·옛 마이그레이션의 원시 SQL)만 이 세트를 집지 않으면 된다 — Gemini 보다 과거면
그 조회의 결과가 바뀌지 않는다. 다른 비 Gemini 시드와 시각이 같아도 다른 체인이라 모델로 거르는 조회에 동률이 생기지 않는다.
시각은 이 리비전이 도는 순간 DB 에서 읽는다. 넣은 뒤 다시 SELECT 해 확인한다: 새 체인 활성 = 시드, Gemini 활성 불변, 레인만
보는 활성 불변. 어긋나면 `RuntimeError`.

**가정이 어긋나면 배포를 멈춘다**(`RuntimeError`, 체인이 한 트랜잭션이라 앞 리비전까지 함께 롤백된다): 그 (레인, haiku_writer)에
세트가 이미 있을 때(초안 포함), Sonnet 활성 세트가 없거나 생성 채널(`system`·`generation`)이 없을 때.

**"활성 데이터 교체"가 아니다** — 새 체인을 더할 뿐 기존 활성 세트는 그대로다. 옛 코드는 (레인, 모델)로 걸러 새 행을 보지 않고,
레인만 보는 옛 조회는 위 게시 시각으로 막힌다. 스키마 변경은 없다(모델 칸은 값 제약이 없는 Text 다).

⚠️ **운영 메모**:
- 🔴 **시드를 손으로 지우지 않는다.** 지우면 다시 배포할 때 `alembic upgrade head` 가 이미 적용된 이 리비전을 건너뛰어 체인이
  빈 채로 남는다(Haiku 방 턴이 환불로 끝나고 어드민 초안 조회가 실패한다). 되돌리려면 아래 `downgrade` 를 쓴다.
- 앞으로 판정·요약·생성 슬롯을 더하는 마이그레이션은 이 체인 둘(story·character × haiku_writer)도 다뤄야 그 체인 게시가 "누락"으로
  막히지 않는다. head 의 체인 커버리지 테스트가 모든 체인 모델의 활성 세트 슬롯을 게시 검증의 기대 집합과 견줘 빠뜨림을 잡는다.

**롤백 순서**: ① 채팅 공개 목록(`CHAT_MODELS_VISIBLE`)에서 `haiku_writer` 를 빼고 재기동한다(저장된 Haiku 방은 기본 모델로 돈다).
② 이미지를 되돌린다 — 데이터는 남긴다(옛 코드에 보이지 않고, 지우면 재배포 때 이 리비전을 건너뛰어 체인이 빈다). ③ downgrade 는
마지막 수단이고 **새 이미지로** 실행한 뒤 이미지를 되돌린다.

`downgrade()`(`delete_seeded_rows`): `model = 'haiku_writer'` 인 **모든** 행을 섹션 → 판 행 → 세트 순으로 지운다 — 시드뿐 아니라
어드민이 그 체인에 만든 초안·게시본까지다. 앞선 시드 리비전들은 시드 뒤 어드민 게시가 있으면 멈췄지만, 이 체인은 이 리비전이
만든 id 라 남기면 다시 올릴 때 "이미 세트가 있다"로 막히고, 이전 코드는 그 체인을 다룰 수 없다. 순서의 이유: 세트를 지우면 판 행
(`prompt_set_semvers`·`prompt_section_semvers` 의 `prompt_set_id`)은 함께 지워지지만 `prompt_set_semvers.base_set_id` 는 함께
지워지지 않는다 — 어드민이 둘째 판을 게시했으면 그 판 행이 시드 세트를 기준판으로 가리켜, 판 행을 남긴 채 세트를 지우면 FK 위반이다.
판 행을 먼저 지우면 그 의존이 없다. 시드가 이미 없으면 아무것도 하지 않는다 — 옛 시드 리비전 테스트의 되돌리기 헬퍼가 여러 번
불러도 같은 결과다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트가 이 모듈을 `importlib` 로 불러 `seed_published_sets`·
`delete_seeded_rows` 를 직접 부른다.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "45e57ce4d815"
down_revision: str | Sequence[str] | None = "02a8ea9563a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MODEL = "haiku_writer"
SOURCE_MODEL = "sonnet"
LANES: tuple[str, ...] = ("story", "character")
_GENERATION_CHANNELS: tuple[str, ...] = ("system", "generation")

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_IDS: dict[str, uuid.UUID] = {
    "story": uuid.UUID("ded7097f-6771-4107-abf9-e1717804db5c"),
    "character": uuid.UUID("04a4d108-58d7-4549-8270-bf4ddb3497b9"),
}
_SECTION_ID_NAMESPACE = uuid.UUID("00a0614e-6f27-418e-b3ca-5421297e2e85")

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE = "Haiku 글쓰기 체인 첫 버전(Sonnet 활성 세트 사본)"

prompt_sets_table = sa.table(
    "prompt_sets",
    sa.column("id", sa.Uuid()),
    sa.column("version", sa.Text()),
    sa.column("status", sa.Text()),
    sa.column("lane", sa.Text()),
    sa.column("model", sa.Text()),
    sa.column("user_label", sa.Text()),
    sa.column("story_assistant_label", sa.Text()),
    sa.column("story_example_label", sa.Text()),
    sa.column("character_assistant_label", sa.Text()),
    sa.column("note", sa.Text()),
    sa.column("published_at", sa.DateTime(timezone=True)),
)

prompt_sections_table = sa.table(
    "prompt_sections",
    sa.column("id", sa.Uuid()),
    sa.column("prompt_set_id", sa.Uuid()),
    sa.column("channel", sa.Text()),
    sa.column("scope", sa.Text()),
    sa.column("slot", sa.Text()),
    sa.column("variant", sa.Text()),
    sa.column("body", sa.Text()),
    sa.column("conditional", sa.Boolean()),
    sa.column("order", sa.Integer()),
)

# 모델로 거르는 활성 규칙 — `load_active_prompt_set`(chat/prompt_builder.py)과 같다.
_ACTIVE_SET_SQL = sa.text(
    "SELECT id, user_label, story_assistant_label, story_example_label, character_assistant_label, published_at"
    " FROM prompt_sets WHERE status = 'published' AND lane = :lane AND model = :model"
    " ORDER BY published_at DESC LIMIT 1"
)
# 모델 열을 모르는 코드(옛 이미지·옛 마이그레이션)의 활성 규칙.
_LANE_ONLY_ACTIVE_SET_SQL = sa.text(
    "SELECT id FROM prompt_sets WHERE status = 'published' AND lane = :lane ORDER BY published_at DESC LIMIT 1"
)
_SECTIONS_SQL = sa.text(
    'SELECT channel, scope, slot, variant, body, conditional, "order" FROM prompt_sections WHERE prompt_set_id = :id'
)
_EXISTING_SETS_SQL = sa.text("SELECT count(*) FROM prompt_sets WHERE lane = :lane AND model = :model")

Row = tuple[str, str, str, str, str, bool, int]


def _section_id(lane: str, channel: str, scope: str, slot: str, variant: str) -> uuid.UUID:
    return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{lane}:{MODEL}:{channel}:{scope}:{slot}:{variant}")


def _rows_of(conn: Connection, set_id: uuid.UUID) -> list[Row]:
    return [tuple(row) for row in conn.execute(_SECTIONS_SQL, {"id": set_id}).fetchall()]


def _assert_source(channels: Sequence[str], *, lane: str) -> None:
    missing = sorted(set(_GENERATION_CHANNELS) - set(channels))
    if missing:
        raise RuntimeError(f"[{lane}/{SOURCE_MODEL}] 활성 세트에 생성 채널이 없다 — 누락 {missing}")


def seed_published_sets(conn: Connection) -> None:
    """레인마다 Sonnet 활성 세트의 사본을 Haiku 글쓰기 체인의 첫 세트로 넣고, 두 활성 조회 규칙으로 다시 확인한다.

    `op` 를 쓰지 않는다 — 테스트가 롤백되는 세션의 커넥션에 `run_sync` 로 부르기 위해서다."""
    for lane in LANES:
        existing = conn.execute(_EXISTING_SETS_SQL, {"lane": lane, "model": MODEL}).scalar_one()
        if existing:
            raise RuntimeError(f"[{lane}/{MODEL}] 이미 세트가 {existing}개 있다")
        source = conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": SOURCE_MODEL}).one_or_none()
        if source is None:
            raise RuntimeError(f"[{lane}/{SOURCE_MODEL}] 활성 세트가 없다")
        rows = _rows_of(conn, source.id)
        _assert_source([row[0] for row in rows], lane=lane)
        gemini = conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": "gemini"}).one()
        lane_only = conn.execute(_LANE_ONLY_ACTIVE_SET_SQL, {"lane": lane}).one().id

        set_id = NEW_SET_IDS[lane]
        # `_next_published_version`(admin/prompts.py)과 같은 규칙 — 전 레인·전 모델 대상.
        latest_version = conn.execute(
            sa.text("SELECT max(CAST(version AS INTEGER)) FROM prompt_sets WHERE status = 'published'")
        ).scalar_one()
        conn.execute(
            sa.insert(prompt_sets_table),
            [
                {
                    "id": set_id,
                    "version": str((latest_version or 0) + 1),
                    "status": "published",
                    "lane": lane,
                    "model": MODEL,
                    "user_label": source.user_label,
                    "story_assistant_label": source.story_assistant_label,
                    "story_example_label": source.story_example_label,
                    "character_assistant_label": source.character_assistant_label,
                    "note": _NOTE,
                    # 그 체인에는 이 세트 하나뿐이라 레인만 보는 조회만 만족하면 된다 — 위 docstring.
                    "published_at": gemini.published_at - timedelta(seconds=1),
                }
            ],
        )
        conn.execute(
            sa.insert(prompt_sections_table),
            [
                {
                    "id": _section_id(lane, channel, scope, slot, variant),
                    "prompt_set_id": set_id,
                    "channel": channel,
                    "scope": scope,
                    "slot": slot,
                    "variant": variant,
                    "body": body,
                    "conditional": conditional,
                    "order": order,
                }
                for channel, scope, slot, variant, body, conditional, order in rows
            ],
        )
        _assign_semver(conn, set_id=set_id)

        chosen = conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": MODEL}).one().id
        gemini_after = conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": "gemini"}).one().id
        lane_only_after = conn.execute(_LANE_ONLY_ACTIVE_SET_SQL, {"lane": lane}).one().id
        if chosen != set_id:
            raise RuntimeError(f"[{lane}/{MODEL}] 새 세트가 활성으로 뽑히지 않는다: 활성={chosen}, 새 세트={set_id}")
        if gemini_after != gemini.id or lane_only_after != lane_only:
            raise RuntimeError(
                f"[{lane}] 기존 활성 세트가 바뀌었다: Gemini {gemini.id}→{gemini_after}, 레인만 {lane_only}→{lane_only_after}"
            )


def upgrade() -> None:
    """Upgrade schema."""
    # 배포 중에도 떠 있는 API 가 prompt_sets 를 읽고 쓴다. 이 리비전은 행만 넣어 오래 쥐는 락이 없지만, 다른 트랜잭션 뒤에서
    # 끝없이 기다리지 않고 5초 안에 실패해 배포가 멈추게 첫 문장으로 건다.
    op.execute("SET LOCAL lock_timeout = '5s'")
    seed_published_sets(op.get_bind())


def delete_seeded_rows(conn: Connection) -> None:
    """위 docstring 의 `downgrade()`. `op` 를 쓰지 않는 이유는 `seed_published_sets` 와 같다."""
    params = {"model": MODEL}
    conn.execute(
        sa.text("DELETE FROM prompt_sections WHERE prompt_set_id IN (SELECT id FROM prompt_sets WHERE model = :model)"),
        params,
    )
    conn.execute(
        sa.text(
            "DELETE FROM prompt_section_semvers WHERE prompt_set_id IN (SELECT id FROM prompt_sets WHERE model = :model)"
        ),
        params,
    )
    conn.execute(sa.text("DELETE FROM prompt_set_semvers WHERE model = :model"), params)
    conn.execute(sa.text("DELETE FROM prompt_sets WHERE model = :model"), params)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    delete_seeded_rows(op.get_bind())


# ---- 판 표 리비전(`d0051f733bb7`)에서 그대로 복사한 판 매기기 블록 -------------------------------------------------


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
                sa.text("SELECT channel, major, minor, patch FROM prompt_section_semvers WHERE prompt_set_id = :id"),
                {"id": base_set_id},
            )
        }
        # 판 행 없이 내용만 있는 기준판 섹션은 물려줄 번호가 없어, 초안에 있으면 기준판에 없던 섹션으로 본다(새로 들어온 섹션처럼
        # 이어 올림). 초안에 없으면 기준판에 있던 내용이 빠진 것이라 빠진 섹션으로 센다.
        full_base_contents = _section_contents(conn, base_set_id)
        base_contents = {channel: content for channel, content in full_base_contents.items() if channel in base_numbers}
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
        } | (set(full_base_contents) - set(contents))
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
