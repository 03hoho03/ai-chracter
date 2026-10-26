"""novel rating rule channel

Revision ID: e4df46a80bfa
Revises: fe3df6f8e4d5
Create Date: 2026-10-26 12:10:00.000000

소설 호출이 붙이는 등급 규칙과 원문 줄 화자 라벨을 `novel` 레인 세트로 옮긴다. 이 리비전 전 코드는 둘을 소설 원작 종류(스토리·
캐릭터) 채팅 레인의 Gemini 활성 세트에서 빌려 읽었다 — 그래서 채팅 문안을 고치면 소설 글도 함께 바뀌었고, 소설 레인만 따로 손질할
수 없었다. 이 리비전 뒤 코드는 소설 세트에서만 읽는다.

**심는 것**: 소설 레인 세 체인(gemini·sonnet·opus)마다 새 published 세트 하나.
- 섹션: 그 체인 활성 세트의 행 전부(본문·conditional·order 바이트 사본 — 운영자가 어드민에서 고친 문안 포함) + 새 채널
  `novelize_rating` 두 행. scope `story` 행은 (story, gemini) 활성 세트의 `system/rule_rating` 본문·conditional, scope `character`
  행은 (character, gemini) 활성 세트의 것을 바이트 그대로 옮긴다(slot `rule_rating`, variant 없음, order 0). 세 체인 모두 같은
  두 행이다 — 이 리비전 전 코드는 소설 모델과 무관하게 채팅 Gemini 세트의 등급 규칙을 붙였다.
- 라벨: `user_label` 은 채팅 story 세트 값(= character 세트 값), `story_assistant_label` 은 채팅 **story** 세트 값,
  `character_assistant_label` 은 채팅 **character** 세트 값, `story_example_label` 은 소설 원본 값 그대로(읽는 코드가 없다). 지금
  소설 세트의 라벨 칸은 스토리 채팅 세트의 사본이라, 캐릭터 라벨을 스토리 세트에서 가져오면 캐릭터 원작 소설의 원문 줄이 바뀐다.
- 그래서 이 리비전 전 코드가 채팅 세트에서 읽어 만든 글과 이 리비전 뒤 코드가 소설 세트에서 읽어 만든 글이 바이트까지 같다.

**가정 검사**(어긋나면 아무것도 넣지 않고 `RuntimeError` — 체인이 한 트랜잭션이라 앞 리비전까지 함께 롤백된다): 이 리비전의 세트가
이미 있을 때, (story, gemini)·(character, gemini) 활성이 없을 때, 각 채팅 활성의 `system/rule_rating` 행이 정확히 하나·scope
`both`·variant 없음이 아닐 때, **두 채팅 활성의 `user_label` 이 다를 때**(소설 세트 칸은 하나뿐이라 한쪽 원작의 원문 줄이 바뀐다),
옮길 라벨이 비었거나 개행·`:` 를 담을 때(이 리비전 뒤 소설 레인 게시도 라벨 검사를 받으므로 게시가 막힐 값을 미리 거른다), 소설 세
체인 중 활성이 없거나 활성에 이미 `novelize_rating` 행이 있거나 `novelize_chapter` 행이 없을 때. 레인 전체에서 가장 나중 게시본이
Gemini 세트인지는 보지 않는다 — 활성은 (레인, 모델)로 골라지고 운영에서는 그렇지 않을 수 있다. 넣은 뒤 새 등급 규칙 행의
`md5(body)` 를 원본 채팅 행과 SQL 로 다시 견준다.

**`published_at` — `max(now, 그 체인 활성 + 1초)`.** 넣은 뒤 그 체인 활성을 다시 SELECT 해 새 세트가 아니면 `RuntimeError`.

**판**: 세트마다 넣은 직후 아래 `_assign_semver` 블록(판 표 리비전 `d0051f733bb7` 에서 그대로 복사)으로 매긴다. `novelize_rating`
은 체인에 처음 들어오는 섹션이라 minor 로 고른다. 라벨이 바뀐 체인은 `speaker_labels` 가 기본 단계(patch)로 함께 오른다 — 라벨이
그대로인 체인에서 그 이름을 단계에 넣으면 블록이 작성 실수로 멈추므로 넣지 않는다.

**초안**: 소설 레인 초안(모델 무관)에 `novelize_rating` 행이 하나도 없으면 같은 두 행을 **제자리에서** 넣는다. 그리고 소설 초안의
라벨 셋을 위 값으로 바꾼다 — 이 리비전 전에는 그 칸을 어디서도 읽지 않았고 어드민 화면이 숨겼으므로 잃는 값이 없다. 채팅 초안은
건드리지 않는다.

**PK**: 세트는 리터럴 UUID(`NEW_SET_IDS`), 섹션은 새 namespace 의 `uuid5("{model}:{channel}:{scope}:{slot}:{variant}")`, 초안 행은 같은
이름 앞에 `draft:` 를 붙인다. `version` 은 전 레인·전 모델 published 최대 + 1 을 gemini·sonnet·opus 순서로.

**옛 이미지가 이 데이터 위에서 도는 구간**(배포 중 겹침, 이미지만 되돌린 동안): 옛 코드는 계속 채팅 Gemini 세트에서 라벨·등급
규칙을 읽고, 새 세트의 다른 행은 원본 바이트 사본이라 렌더가 그대로다. 옛 코드의 게시 검증이 `novelize_rating` 을 "잉여"로 거부해
**소설 레인 세 체인의 어드민 게시만** 막힌다(재배포로 풀린다). 되돌린 동안은 소설 레인 등급 규칙을 고쳐도 소설 글에 반영되지
않는다.

⚠️ **운영 메모**:
- 배포 전부터 열어 둔 어드민 소설 탭에서 저장하면 초안이 섹션 전체 교체로 새 행을 잃고 게시가 "누락"으로 막힌다. **배포 뒤에는
  편집 탭을 새로고침한다.**
- 🔴 **시드를 손으로 지우지 않는다.** 되돌리려면 아래 `downgrade` 를 쓴다.

**롤백 순서**: 이미지를 먼저 되돌린다(데이터는 남겨 둔다 — 옛 코드가 이 데이터 위에서 도는 동안의 동작은 위에 적었다). 행까지
지워야 하면 그 뒤, 새 이미지에 든 마이그레이션 파일로 등급 규칙 리비전(`e4df46a80bfa`) → Claude 체인 채널 리비전(`fe3df6f8e4d5`)
순으로 downgrade 한다 — 옛 이미지에는 두 파일이 없어 그 이미지로는 내릴 수 없다.

`downgrade()`(`delete_seeded_rows`): 체인마다 시드 뒤에 어드민이 게시한 세트가 있거나, 시드를 기준판으로 가리키는 판 행이 있으면
아무것도 지우지 않고 `RuntimeError` 로 멈춘다. 없으면 시드의 섹션 → 세트(판 행은 함께 지워진다)와 소설 초안의 `novelize_rating`
행을 지운다. 초안 라벨은 되돌리지 않는다(이전 코드는 소설 라벨을 읽지 않는다). 시드가 이미 없으면 아무것도 하지 않는다 — 다른
레인 테스트의 되돌리기 헬퍼가 여러 번 불러도 같은 결과다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트가 이 모듈을 `importlib` 로 불러 `seed_published_sets`·`_patch_drafts`·
`delete_seeded_rows` 를 직접 부른다.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4df46a80bfa"
down_revision: str | Sequence[str] | None = "fe3df6f8e4d5"
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

LANE = "novel"
MODELS: tuple[str, ...] = ("gemini", "sonnet", "opus")
CHAT_MODEL = "gemini"
SCOPES: tuple[str, ...] = ("story", "character")

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_IDS: dict[str, uuid.UUID] = {
    "gemini": uuid.UUID("2ab6e47c-3ffa-4995-95d1-9394a44c81db"),
    "sonnet": uuid.UUID("e5912ca0-4461-4bca-8023-1e240b450c34"),
    "opus": uuid.UUID("6c5a909c-26ee-4acb-af64-e00436bfc57e"),
}
_SECTION_ID_NAMESPACE = uuid.UUID("326bc3ea-dd53-4c43-8b37-650d21c1ffb1")

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE = "등급 규칙·화자 라벨을 소설 레인으로 옮김(채팅 Gemini 활성 세트 값 사본)"

RATING_CHANNEL = "novelize_rating"
RATING_SLOT = "rule_rating"
# 소설 문안 세트인지 보는 표지 — 화 생성 채널이 없는 세트는 소설 레인 문안이 아니다.
CHAPTER_CHANNEL = "novelize_chapter"

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
_RATING_SQL = sa.text(
    "SELECT scope, variant, body, conditional FROM prompt_sections"
    " WHERE prompt_set_id = :id AND channel = 'system' AND slot = :slot"
)


def seed_time(chain_at: datetime, now: datetime) -> datetime:
    """새 세트 게시 시각 — 그 체인에서 가장 나중이 되게 `max(now, 그 체인 활성 + 1초)`."""
    return max(now, chain_at + timedelta(seconds=1))


def _section_id(model: str, channel: str, scope: str, slot: str, variant: str, *, prefix: str = "") -> uuid.UUID:
    return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{prefix}{model}:{channel}:{scope}:{slot}:{variant}")


def _rows_of(conn: Connection, set_id: uuid.UUID) -> list[Row]:
    return [tuple(row) for row in conn.execute(_SECTIONS_SQL, {"id": set_id}).fetchall()]


def _section_dicts(rows: Sequence[Row], *, model: str, set_id: uuid.UUID, prefix: str = "") -> list[dict[str, object]]:
    return [
        {
            "id": _section_id(model, channel, scope, slot, variant, prefix=prefix),
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


def _label_value(value: str, name: str) -> str:
    if not value.strip() or "\n" in value or ":" in value:
        raise RuntimeError(f"옮길 라벨 {name} 이(가) 비었거나 개행·':' 를 담는다 — 소설 레인 게시가 막힐 값이다")
    return value


def _chat_sources(conn: Connection) -> tuple[list[Row], dict[str, str]]:
    """채팅 두 레인 Gemini 활성 세트에서 등급 규칙 두 행(story·character 순)과 옮길 라벨 셋을 읽는다."""
    chat_sets = {}
    rating_rows: list[Row] = []
    for scope in SCOPES:
        chat_set = conn.execute(_ACTIVE_SET_SQL, {"lane": scope, "model": CHAT_MODEL}).first()
        if chat_set is None:
            raise RuntimeError(f"[{scope}/{CHAT_MODEL}] 활성 세트가 없다")
        rows = conn.execute(_RATING_SQL, {"id": chat_set.id, "slot": RATING_SLOT}).fetchall()
        if len(rows) != 1 or rows[0].scope != "both" or rows[0].variant != "":
            raise RuntimeError(
                f"[{scope}/{CHAT_MODEL}] system/{RATING_SLOT} 행이 scope both·variant 없음 한 행이 아니다({len(rows)}행)"
            )
        rating_rows.append((RATING_CHANNEL, scope, RATING_SLOT, "", rows[0].body, rows[0].conditional, 0))
        chat_sets[scope] = chat_set
    if chat_sets["story"].user_label != chat_sets["character"].user_label:
        raise RuntimeError(
            "스토리·캐릭터 채팅 Gemini 활성 세트의 user_label 이 다르다 — 소설 세트에는 칸이 하나뿐이라 한쪽 원작의 원문 줄이"
            " 바뀐다. 아무것도 넣지 않았다"
        )
    labels = {
        "user_label": _label_value(chat_sets["story"].user_label, "user_label"),
        "story_assistant_label": _label_value(chat_sets["story"].story_assistant_label, "story_assistant_label"),
        "character_assistant_label": _label_value(
            chat_sets["character"].character_assistant_label, "character_assistant_label"
        ),
    }
    return rating_rows, labels


def seed_published_sets(conn: Connection) -> None:
    """소설 세 체인에 새 세트를 넣고 판을 매긴 뒤, 체인마다 활성이 새 세트인지와 등급 규칙 행이 원본과 같은지 다시 확인한다.

    `op` 를 쓰지 않는다 — 테스트가 롤백되는 세션의 커넥션에 `run_sync` 로 부르기 위해서다."""
    existing = conn.execute(
        sa.select(sa.func.count()).select_from(prompt_sets_table).where(
            prompt_sets_table.c.id.in_(list(NEW_SET_IDS.values()))
        )
    ).scalar_one()
    if existing:
        raise RuntimeError(f"이 리비전의 세트가 이미 있다({existing}개)")
    rating_rows, labels = _chat_sources(conn)
    sources = {}
    for model in MODELS:
        source = conn.execute(_ACTIVE_SET_SQL, {"lane": LANE, "model": model}).first()
        if source is None:
            raise RuntimeError(f"[{LANE}/{model}] 활성 세트가 없다")
        source_rows = _rows_of(conn, source.id)
        channels = {row[0] for row in source_rows}
        if RATING_CHANNEL in channels:
            raise RuntimeError(f"[{LANE}/{model}] 활성 세트에 {RATING_CHANNEL} 행이 이미 있다")
        if CHAPTER_CHANNEL not in channels:
            raise RuntimeError(f"[{LANE}/{model}] 활성 세트에 {CHAPTER_CHANNEL} 행이 없다")
        sources[model] = (source, source_rows)

    now = datetime.now(UTC)
    for model in MODELS:
        source, source_rows = sources[model]
        set_id = NEW_SET_IDS[model]
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
                    "lane": LANE,
                    "model": model,
                    "user_label": labels["user_label"],
                    "story_assistant_label": labels["story_assistant_label"],
                    "story_example_label": source.story_example_label,
                    "character_assistant_label": labels["character_assistant_label"],
                    "note": _NOTE,
                    "published_at": seed_time(source.published_at, now),
                }
            ],
        )
        conn.execute(
            sa.insert(prompt_sections_table),
            _section_dicts([*source_rows, *rating_rows], model=model, set_id=set_id),
        )
        _assign_semver(conn, set_id=set_id, levels={RATING_CHANNEL: "minor"})

        chosen = conn.execute(_ACTIVE_SET_SQL, {"lane": LANE, "model": model}).one().id
        if chosen != set_id:
            raise RuntimeError(f"[{LANE}/{model}] 새 세트가 활성으로 뽑히지 않는다: 활성={chosen}, 새 세트={set_id}")
        _check_rating_copy(conn, set_id)


def _check_rating_copy(conn: Connection, set_id: uuid.UUID) -> None:
    """새 세트의 등급 규칙 행 본문이 원작 종류마다 채팅 Gemini 활성 행과 바이트 같은지 DB 의 md5 로 다시 본다."""
    for scope in SCOPES:
        copied = conn.execute(
            sa.text(
                "SELECT md5(body) FROM prompt_sections WHERE prompt_set_id = :id AND channel = :channel"
                " AND scope = :scope AND slot = :slot"
            ),
            {"id": set_id, "channel": RATING_CHANNEL, "scope": scope, "slot": RATING_SLOT},
        ).scalar_one()
        chat_set_id = conn.execute(_ACTIVE_SET_SQL, {"lane": scope, "model": CHAT_MODEL}).one().id
        original = conn.execute(
            sa.text("SELECT md5(body) FROM prompt_sections WHERE prompt_set_id = :id AND channel = 'system' AND slot = :slot"),
            {"id": chat_set_id, "slot": RATING_SLOT},
        ).scalar_one()
        if copied != original:
            raise RuntimeError(f"[{LANE}] 옮긴 {scope} 등급 규칙이 원본과 다르다")


def _patch_drafts(conn: Connection) -> list[str]:
    """소설 레인 초안마다 등급 규칙 행이 하나도 없으면 두 행을 제자리에서 넣고, 소설 초안 라벨을 옮긴 값으로 바꾼다. 행을 넣은
    모델 목록을 돌려준다. `op` 를 쓰지 않는 이유는 `seed_published_sets` 와 같다."""
    drafts = conn.execute(
        sa.text("SELECT id, model FROM prompt_sets WHERE status = 'draft' AND lane = :lane ORDER BY model"),
        {"lane": LANE},
    ).fetchall()
    if not drafts:
        return []
    rating_rows, labels = _chat_sources(conn)
    patched: list[str] = []
    for draft in drafts:
        present = {row[0] for row in _rows_of(conn, draft.id)}
        if RATING_CHANNEL not in present:
            conn.execute(
                sa.insert(prompt_sections_table),
                _section_dicts(rating_rows, model=draft.model, set_id=draft.id, prefix="draft:"),
            )
            patched.append(draft.model)
    conn.execute(
        sa.update(prompt_sets_table)
        .where(prompt_sets_table.c.status == "draft", prompt_sets_table.c.lane == LANE)
        .values(**labels)
    )
    return patched


def upgrade() -> None:
    # 배포 중에도 떠 있는 API 가 prompt_sets 를 읽고 쓴다. 이 리비전은 행만 넣고 초안 라벨만 바꿔 오래 쥐는 락이 없지만, 다른
    # 트랜잭션 뒤에서 끝없이 기다리지 않고 5초 안에 실패해 배포가 멈추게 첫 문장으로 건다.
    op.execute("SET LOCAL lock_timeout = '5s'")
    bind = op.get_bind()
    seed_published_sets(bind)
    _patch_drafts(bind)


def _delete_draft_rows(conn: Connection) -> None:
    conn.execute(
        sa.text(
            "DELETE FROM prompt_sections s USING prompt_sets p WHERE p.id = s.prompt_set_id"
            " AND p.status = 'draft' AND p.lane = :lane AND s.channel = :channel"
        ),
        {"lane": LANE, "channel": RATING_CHANNEL},
    )


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
    for model in MODELS:
        later = conn.execute(
            sa.text(
                "SELECT count(*) FROM prompt_sets WHERE status = 'published' AND lane = :lane AND model = :model"
                " AND id <> :seed AND published_at > (SELECT published_at FROM prompt_sets WHERE id = :seed)"
            ),
            {"lane": LANE, "model": model, "seed": NEW_SET_IDS[model]},
        ).scalar_one()
        if later:
            raise RuntimeError(
                f"시드 뒤에 어드민이 게시한 세트가 있다({LANE}/{model} {later}개) — 되돌려도 그 게시가 활성으로 남아 서빙 문안이"
                " 되돌아가지 않고, 이전 코드의 소설 레인 게시가 막힌다. 아무것도 지우지 않았다"
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
            " 서빙 문안이 되돌아가지 않는다. 아무것도 지우지 않았다"
        )
    conn.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.prompt_set_id.in_(seeded)))
    conn.execute(sa.delete(prompt_sets_table).where(prompt_sets_table.c.id.in_(seeded)))
    _delete_draft_rows(conn)


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
