"""chat drop frozen novel rows

Revision ID: 7caed2db87dc
Revises: 296e34a7182f
Create Date: 2026-10-27 12:00:00.000000

채팅 두 레인(story·character)의 Gemini 체인 세트에 남겨 둔 옛 소설화 세 채널(`novelize_boundary`·`novelize_chapter`·
`novelize_revise`) 행을 뺀 새 세트를 게시한다. 소설 호출은 이미 `novel` 레인 세트에서만 문안을 읽는다 — 채팅 세트의 이 행은 그보다
옛 이미지로 되돌렸을 때 옛 코드가 읽을 값이라 지우지 않고 얼려 두었고, 그래서 채팅 Gemini 체인 게시는 이 행을 계속 요구하고 어드민
저장·게시·복원이 직전 게시본의 값을 갈아 끼웠다. 이 리비전과 같은 배포의 코드는 채팅 레인 기대 집합에서 세 채널을 빼고 갈아 끼우기를
없앤다. 채팅 렌더는 이 세 채널을 읽지 않으므로(채팅 생성·판정·요약은 채널 이름을 지정해 렌더한다) 채팅 프롬프트는 바이트까지 그대로다.

**대상**: (story, gemini)·(character, gemini) **활성** 세트 둘만. Claude·판정 전용 채팅 체인에는 처음부터 이 행이 없다.

**새 세트는 그 체인 활성 세트의 바이트 사본에서 세 채널 행만 뺀 것이다** — 라벨 넷과 다른 모든 행(운영자가 어드민에서 고친 문안
포함)의 본문·conditional·order 가 그대로 옮겨진다(id·version·note·게시 시각만 새 값). 게시된 세트는 고치지 않는다.

**가정 검사**(어긋나면 아무것도 넣지 않고 `RuntimeError` — 체인이 한 트랜잭션이라 앞 리비전까지 함께 롤백된다): 이 리비전의 세트가
이미 있을 때, 두 체인 중 활성 세트가 없을 때, 활성에 세 채널 중 하나라도 없을 때. 레인 전체에서 가장 나중 게시본이 Gemini 세트인지는
보지 않는다 — 활성은 (레인, 모델)로 골라지고, 운영에서는 Claude 체인 세트가 레인의 가장 나중 게시본일 수 있어 그 검사를 두면
업그레이드가 멈춘다. 넣은 뒤 남은 행이 원본 활성의 같은 행과 바이트 같은지 DB 의 `md5` 로 다시 견준다.

**`published_at` — `max(now, 그 체인 활성 + 1초)`.** 넣은 뒤 그 체인 활성을 다시 SELECT 해 새 세트가 아니면 `RuntimeError`.

**판**: 세트마다 넣은 직후 아래 `_assign_semver` 블록(판 표 리비전 `d0051f733bb7` 에서 그대로 복사)으로 매긴다. 빠진 세 채널만 바뀐
섹션이라 기본 단계(patch)로 오른다 — 체인이 하는 일은 그대로다.

**초안**: 두 체인의 초안이 있으면 그 초안의 세 채널 행을 지운다(다른 행은 건드리지 않는다). 초안 행은 옛 코드가 저장 때마다 활성
값으로 다시 채우던 것이라 잃는 운영자 편집이 없고, 남겨 두면 이 배포 뒤 게시가 "잉여"로 막힌다.

**PK**: 세트는 리터럴 UUID(`NEW_SET_IDS`), 섹션은 새 namespace 의 `uuid5("{lane}:{model}:{channel}:{scope}:{slot}:{variant}")`.
`version` 은 전 레인·전 모델 published 최대 + 1 을 story·character 순서로.

**옛 이미지가 이 데이터 위에서 도는 구간**(배포 중 겹침, 이미지만 되돌린 동안): 소설 문안을 소설 레인에서 읽는 이미지는 채팅·소설
렌더가 그대로다. 그 이미지의 게시 검증은 채팅 Gemini 체인에 세 채널을 요구하므로 **채팅 두 레인 Gemini 체인의 어드민 게시만**
"누락"으로 막힌다(재배포로 풀린다). 소설 문안을 채팅 레인에서 읽던 더 옛 이미지는 이 데이터 위에서 소설 호출의 렌더가 비어 실패한다
— 그 이미지로 되돌려야 하면 먼저 아래 `downgrade` 로 이 리비전을 내린다.

⚠️ **운영 메모**:
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 배포 직후 잠시 옛 세트를 읽지만 채팅 렌더는 같다.
- 🔴 **시드를 손으로 지우지 않는다.** 되돌리려면 아래 `downgrade` 를 쓴다.

**롤백 순서**: 이미지를 먼저 되돌린다(데이터는 남겨 둔다 — 위 옛 이미지 구간). 게시까지 되살리거나 소설을 채팅 레인에서 읽던 이미지로
가야 하면 **이 리비전 파일이 있는 이미지로** `downgrade` 를 실행한 뒤 이미지를 되돌린다.

`downgrade()`(`delete_seeded_rows`): 시드 뒤에 어드민이 두 체인 중 하나에 새 버전을 게시했거나, 시드를 기준판으로 가리키는 판 행이
있으면 아무것도 지우지 않고 `RuntimeError` 로 멈춘다 — 되돌려도 그 게시본(세 채널이 없는)이 활성으로 남아 서빙 문안이 되돌아가지
않고 옛 코드의 그 체인 게시가 "누락"으로 막혀, 이 리비전은 되돌릴 수 없다. 없으면 시드의 섹션 → 세트(판 행은 함께 지워진다)를
지운다. 지운 초안 행은 되살리지 않는다 — 옛 코드가 초안을 저장할 때 활성 세트 값으로 다시 채운다. 시드가 이미 없으면 아무것도 하지
않는다 — 다른 리비전 테스트의 되돌리기 헬퍼가 여러 번 불러도 같은 결과다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트가 이 모듈을 `importlib` 로 불러 `seed_published_sets`·`_delete_draft_rows`·
`delete_seeded_rows` 를 직접 부른다.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7caed2db87dc"
down_revision: str | Sequence[str] | None = "296e34a7182f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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

LANES: tuple[str, ...] = ("story", "character")
MODEL = "gemini"
# 빼는 채널 — 채팅 레인에 얼려 둔 옛 소설화 채널 셋.
DROPPED_CHANNELS: tuple[str, ...] = ("novelize_boundary", "novelize_chapter", "novelize_revise")

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_IDS: dict[str, uuid.UUID] = {
    "story": uuid.UUID("cfa0ff1d-a39d-4237-85b6-ff651fdeaa75"),
    "character": uuid.UUID("e0f6b7fc-4749-4d61-9ca5-57c610896568"),
}
_SECTION_ID_NAMESPACE = uuid.UUID("5e4fb4ae-f7db-4e59-b602-0671d36d8720")

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE = "채팅 레인에 얼려 둔 옛 소설화 세 채널을 뺌(나머지는 활성 세트 사본)"

Row = tuple[str, str, str, str, str, bool, int]

# 모델로 거르는 활성 규칙 — `load_active_prompt_set`(chat/prompt_builder.py)과 같다.
_ACTIVE_SET_SQL = sa.text(
    "SELECT id, user_label, story_assistant_label, story_example_label, character_assistant_label,"
    " published_at"
    " FROM prompt_sets WHERE status = 'published' AND lane = :lane AND model = :model"
    " ORDER BY published_at DESC LIMIT 1"
)
_SECTIONS_SQL = sa.text(
    'SELECT channel, scope, slot, variant, body, conditional, "order"'
    " FROM prompt_sections WHERE prompt_set_id = :id"
)
# 남긴 행의 지문 — (channel, scope, slot, variant) 순으로 이은 md5 를 DB 가 계산한다.
_KEPT_FINGERPRINT_SQL = sa.text(
    "SELECT count(*), md5(string_agg("
    "channel || '|' || scope || '|' || slot || '|' || variant || '|' || md5(body) || '|' || conditional::text"
    " || '|' || \"order\"::text, ',' ORDER BY channel, scope, slot, variant))"
    " FROM prompt_sections WHERE prompt_set_id = :id AND NOT (channel IN :dropped)"
).bindparams(sa.bindparam("dropped", expanding=True))


def seed_time(chain_at: datetime, now: datetime) -> datetime:
    """새 세트 게시 시각 — 그 체인에서 가장 나중이 되게 `max(now, 그 체인 활성 + 1초)`."""
    return max(now, chain_at + timedelta(seconds=1))


def _section_id(lane: str, channel: str, scope: str, slot: str, variant: str) -> uuid.UUID:
    return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{lane}:{MODEL}:{channel}:{scope}:{slot}:{variant}")


def _rows_of(conn: Connection, set_id: uuid.UUID) -> list[Row]:
    return [tuple(row) for row in conn.execute(_SECTIONS_SQL, {"id": set_id}).fetchall()]


def _section_dicts(rows: Sequence[Row], *, lane: str, set_id: uuid.UUID) -> list[dict[str, object]]:
    return [
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
    ]


def seed_published_sets(conn: Connection) -> None:
    """두 체인에 새 세트를 넣고 판을 매긴 뒤, 체인마다 활성이 새 세트인지와 남긴 행이 원본과 같은지 다시 확인한다.

    `op` 를 쓰지 않는다 — 테스트가 롤백되는 세션의 커넥션에 `run_sync` 로 부르기 위해서다."""
    existing = conn.execute(
        sa.select(sa.func.count()).select_from(prompt_sets_table).where(
            prompt_sets_table.c.id.in_(list(NEW_SET_IDS.values()))
        )
    ).scalar_one()
    if existing:
        raise RuntimeError(f"이 리비전의 세트가 이미 있다({existing}개)")
    # 넣기 전에 두 체인을 모두 검사한다 — 하나라도 어긋나면 아무것도 넣지 않은 채 멈춘다.
    sources = {}
    for lane in LANES:
        source = conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": MODEL}).first()
        if source is None:
            raise RuntimeError(f"[{lane}/{MODEL}] 활성 세트가 없다")
        source_rows = _rows_of(conn, source.id)
        missing = sorted(set(DROPPED_CHANNELS) - {row[0] for row in source_rows})
        if missing:
            raise RuntimeError(f"[{lane}/{MODEL}] 활성 세트에 뺄 소설 채널 행이 없다: {missing}")
        sources[lane] = (source, source_rows)

    now = datetime.now(UTC)
    for lane in LANES:
        source, source_rows = sources[lane]
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
                    "published_at": seed_time(source.published_at, now),
                }
            ],
        )
        kept = [row for row in source_rows if row[0] not in DROPPED_CHANNELS]
        conn.execute(sa.insert(prompt_sections_table), _section_dicts(kept, lane=lane, set_id=set_id))
        _assign_semver(conn, set_id=set_id)

        chosen = conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": MODEL}).one().id
        if chosen != set_id:
            raise RuntimeError(f"[{lane}/{MODEL}] 새 세트가 활성으로 뽑히지 않는다: 활성={chosen}, 새 세트={set_id}")
        _check_kept_copy(conn, lane=lane, source_id=source.id, set_id=set_id)


def _check_kept_copy(conn: Connection, *, lane: str, source_id: uuid.UUID, set_id: uuid.UUID) -> None:
    """새 세트의 행이 원본 활성에서 세 채널을 뺀 행과 바이트 같은지, 새 세트에 세 채널 행이 없는지 DB 의 md5 로 다시 본다."""
    params = {"dropped": list(DROPPED_CHANNELS)}
    source = conn.execute(_KEPT_FINGERPRINT_SQL, {"id": source_id, **params}).one()
    seeded = conn.execute(_KEPT_FINGERPRINT_SQL, {"id": set_id, **params}).one()
    if tuple(seeded) != tuple(source):
        raise RuntimeError(f"[{lane}/{MODEL}] 새 세트의 남긴 행이 원본 활성과 다르다")
    total = conn.execute(
        sa.select(sa.func.count()).select_from(prompt_sections_table).where(
            prompt_sections_table.c.prompt_set_id == set_id
        )
    ).scalar_one()
    if total != seeded[0]:
        raise RuntimeError(f"[{lane}/{MODEL}] 새 세트에 뺄 소설 채널 행이 남았다")


def _delete_draft_rows(conn: Connection) -> list[str]:
    """두 체인 초안의 세 채널 행을 지우고, 행을 지운 레인 목록을 돌려준다. `op` 를 쓰지 않는 이유는 `seed_published_sets` 와
    같다. PK 가 아니라 레인·모델·채널로 찾는다 — 초안 저장이 섹션을 통째로 갈아 PK 가 바뀌어 있을 수 있다."""
    found = conn.execute(
        sa.text(
            "SELECT DISTINCT p.id, p.lane FROM prompt_sections s JOIN prompt_sets p ON p.id = s.prompt_set_id"
            " WHERE p.status = 'draft' AND p.lane IN :lanes AND p.model = :model AND s.channel IN :dropped"
            " ORDER BY p.lane"
        ).bindparams(sa.bindparam("lanes", expanding=True), sa.bindparam("dropped", expanding=True)),
        {"lanes": list(LANES), "model": MODEL, "dropped": list(DROPPED_CHANNELS)},
    ).fetchall()
    for draft_id, _lane in found:
        conn.execute(
            sa.delete(prompt_sections_table).where(
                prompt_sections_table.c.prompt_set_id == draft_id,
                prompt_sections_table.c.channel.in_(DROPPED_CHANNELS),
            )
        )
    return [lane for _id, lane in found]


def upgrade() -> None:
    # 배포 중에도 떠 있는 API 가 prompt_sets 를 읽고 쓴다. 이 리비전은 행만 넣고 초안 행 몇 개만 지워 오래 쥐는 락이 없지만, 다른
    # 트랜잭션 뒤에서 끝없이 기다리지 않고 5초 안에 실패해 배포가 멈추게 첫 문장으로 건다.
    op.execute("SET LOCAL lock_timeout = '5s'")
    bind = op.get_bind()
    seed_published_sets(bind)
    _delete_draft_rows(bind)


def delete_seeded_rows(conn: Connection) -> None:
    """위 docstring 의 `downgrade()`. `op` 를 쓰지 않는 이유는 `seed_published_sets` 와 같다."""
    seeded = [
        row.id
        for row in conn.execute(
            sa.select(prompt_sets_table.c.id).where(prompt_sets_table.c.id.in_(list(NEW_SET_IDS.values())))
        )
    ]
    if not seeded:
        return
    later: list[str] = []
    for lane in LANES:
        count = conn.execute(
            sa.text(
                "SELECT count(*) FROM prompt_sets WHERE status = 'published' AND lane = :lane AND model = :model"
                " AND id <> :seed AND published_at > (SELECT published_at FROM prompt_sets WHERE id = :seed)"
            ),
            {"lane": lane, "model": MODEL, "seed": NEW_SET_IDS[lane]},
        ).scalar_one()
        if count:
            later.append(f"{lane}/{MODEL} {count}개")
    if later:
        raise RuntimeError(
            f"시드 뒤에 어드민이 게시한 세트가 있다({', '.join(later)}) — 되돌려도 소설 채널이 없는 그 게시본이 활성으로 남아 서빙"
            " 문안이 되돌아가지 않고 이전 코드의 그 체인 게시가 막힌다. 이 리비전은 되돌릴 수 없다. 아무것도 지우지 않았다"
        )
    referenced = conn.execute(
        sa.text("SELECT count(*) FROM prompt_set_semvers WHERE base_set_id IN :seeded").bindparams(
            sa.bindparam("seeded", expanding=True)
        ),
        {"seeded": seeded},
    ).scalar_one()
    if referenced:
        raise RuntimeError(
            f"이 리비전의 세트를 기준판으로 가리키는 판 행이 있다({referenced}개) — 그 위에 나중 게시가 쌓였다는 뜻이라 지워도"
            " 서빙 문안이 되돌아가지 않는다. 이 리비전은 되돌릴 수 없다. 아무것도 지우지 않았다"
        )
    conn.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.prompt_set_id.in_(seeded)))
    conn.execute(sa.delete(prompt_sets_table).where(prompt_sets_table.c.id.in_(seeded)))


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
                sa.text(
                    "SELECT channel, major, minor, patch FROM prompt_section_semvers WHERE prompt_set_id = :id"
                ),
                {"id": base_set_id},
            )
        }
        # 판 행 없이 내용만 있는 기준판 섹션은 물려줄 번호가 없어, 초안에 있으면 기준판에 없던 섹션으로 본다(새로 들어온 섹션처럼
        # 이어 올림). 초안에 없으면 기준판에 있던 내용이 빠진 것이라 빠진 섹션으로 센다.
        full_base_contents = _section_contents(conn, base_set_id)
        base_contents = {
            channel: content for channel, content in full_base_contents.items() if channel in base_numbers
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
