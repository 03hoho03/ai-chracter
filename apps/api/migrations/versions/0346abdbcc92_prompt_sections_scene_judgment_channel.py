"""prompt sections scene judgment channel

Revision ID: 0346abdbcc92
Revises: 677dd73e2ab9
Create Date: 2026-10-18 20:38:16.650881

장면 헤더 판정(스토리 방에서 매 턴 응답 뒤 지금 장면의 장소·시간을 짧게 적는 판정)의 문안 채널 `scene_judgment` 를 story 레인의
네 체인(gemini·sonnet·opus·haiku)에 넣는다. 판정은 스탯 판정 모델 설정으로 체인을 고르므로 그 설정이 어느 체인을 고르든 그 세트에
문안이 있어야 한다 — 하나라도 빠지면 그 체인 게시가 슬롯 집합 검사("누락")로 막히고, 그 판정 모델로 렌더하면 빈 문자열이 된다.

**심는 행**(scope `story`): 지시문 `instruction`(order 0), 직전 장면 `previous_scene`(1, conditional — 자리표시자
`{previous_place}`·`{previous_time}`, 둘 다 비면 섹션째 빠진다), 이번 턴 `turn_context`(2 — `{user_label}`·`{user_message}`·
`{assistant_label}`·`{assistant_message}`). 새 채널이라 기준 행이 없어 order 는 고정이다. 네 체인의 새 행은 같은 본문이다.

**새 세트는 그 체인 활성 세트의 바이트 사본에 이 세 행을 더한 것이다** — 라벨·다른 모든 행(운영자가 어드민에서 고친 문안, 얼려
둔 소설 행 포함)의 본문·conditional·order 가 그대로 옮겨진다. **게시된 세트는 고치지 않는다.** 그래서 기존 채널의 렌더는 바이트까지
그대로다.

**가정 검사**: 어느 체인의 활성 세트에 `scene_judgment` 행이 이미 있으면 `RuntimeError` 로 배포를 멈춘다. 한 레인의 네 체인을
모두 검사한 뒤에 넣는다(체인이 한 트랜잭션이라 앞 리비전까지 함께 롤백된다).

**`published_at` — 두 활성 조회 규칙을 함께 만족시킨다**(앞의 판정·요약 문안 리비전들과 같은 규칙).
- 레인만 보는 조회(모델 열을 모르는 원시 SQL)는 레인의 최신 게시본을 고른다 — 새 Gemini 세트는 파이썬 `max(now, 원본 + 1초)`.
- 모델로 거르는 조회(`load_active_prompt_set`)는 (레인, 모델)마다 최신 게시본을 고른다 — sonnet·opus·haiku 의 새 세트는 (그 체인
  활성 시각, 새 Gemini 세트 시각)의 **중간값**. 사이에 둘 시각이 없으면 `RuntimeError`.
- 삽입 뒤 두 규칙으로 다시 SELECT 해 확인한다. 어긋나면 `RuntimeError`.
- 그 밖에 멈추는 경우: 이 리비전의 세트가 이미 있을 때, 레인만 보는 조회가 이미 Gemini 가 아닌 세트를 집을 때.

**초안**: story 레인 네 체인 중 초안이 있는 체인은 `scene_judgment` 행이 없을 때만 같은 세 행을 **제자리에서** 넣는다(기존 행은
건드리지 않는다). 이미 있으면 그대로 둔다 — 초안 하나 때문에 배포를 멈출 일은 아니다.

**PK**: 세트는 리터럴 UUID(`NEW_SET_IDS`), 섹션은 새 namespace 의 `uuid5("{lane}:{model}:{channel}:{scope}:{slot}:{variant}")`,
초안 행은 같은 이름 앞에 `draft:` 를 붙인다. `version` 은 전 레인·전 모델 published 최대 + 1 을 gemini·sonnet·opus·haiku 순서로
매긴다(어드민 게시와 같은 규칙).

**문안**은 이 파일의 `*_BODY` 상수가 유일한 소스다.

**옛 이미지가 이 데이터 위에서 도는 구간**(배포 중 겹침, 이미지만 되돌린 동안): 옛 코드는 이 채널을 읽는 코드가 없어 렌더가
바뀌지 않는다. 다만 옛 코드의 게시 검증이 새 세트·초안의 새 행을 "잉여"로 거부해 **story 레인 네 체인의 어드민 게시만** 막힌다.

⚠️ **운영 메모**:
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 배포 직후 최대 300초 동안 새 채널이 없는 옛 세트로 렌더한다. 그동안 장면 판정은
  렌더가 비어 부르지 않고 직전 장면을 이어받는다.
- 배포 전부터 열어 둔 어드민 프롬프트 편집 탭에서 저장하면 초안이 섹션 전체 교체로 새 행을 잃고 게시가 "누락"으로 막힌다.
  **배포 뒤에는 편집 탭을 새로고침한다.** 이 채널 행이 없는 옛 버전을 restore 한 초안도 같은 이유로 게시할 수 없다.
- 직전 장면 body 에서 두 자리표시자를 다 지우면 드롭 조건이 거짓이 되어 첫 턴에도 빈 머리글이 나간다.
- 🔴 **시드를 손으로 지우지 않는다.** 되돌리려면 아래 `downgrade` 를 쓴다.

**롤백 순서**: 1순위는 이미지만 되돌리기다(위 옛 이미지 구간 — 렌더는 그대로, story 레인 어드민 게시만 막힘). 게시까지 되살려야
하면 **이 리비전 파일이 있는 이미지로** `downgrade` 를 실행한 뒤 이미지를 되돌린다.

`downgrade()`(`delete_seeded_rows`): 시드 뒤에 어드민이 네 체인 중 하나에 새 버전을 게시했으면 아무것도 지우지 않고
`RuntimeError` 로 멈춘다 — 되돌려도 그 게시본(새 채널 행이 든)이 활성으로 남아 이전 코드의 그 체인 게시가 "잉여"로 막히고, 무엇을
버릴지는 사람이 정해야 한다. 없으면 리터럴 시드의 섹션 → 세트를 지우고(이전 활성 세트는 처음부터 이 행이 없다), story 레인 초안의
이 채널 행을 지운다(PK 가 아니라 레인·채널로 찾는다 — 초안 저장이 섹션을 통째로 갈아 PK 가 바뀌어 있을 수 있다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트(`tests/test_scene_judgment_prompt_migration.py`)가 이 모듈을
`importlib` 로 불러 `seed_published_sets`·`_patch_drafts`·`delete_seeded_rows`·`_delete_draft_rows` 를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0346abdbcc92'
down_revision: str | Sequence[str] | None = '677dd73e2ab9'
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

LANE = "story"
_GEMINI = "gemini"
# 판정 문안이 있는 네 체인. Gemini 가 맨 앞이어야 한다(다른 체인의 게시 시각이 새 Gemini 세트 시각에 기댄다).
_MODELS: tuple[str, ...] = (_GEMINI, "sonnet", "opus", "haiku")

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_IDS: dict[tuple[str, str], uuid.UUID] = {
    ("story", "gemini"): uuid.UUID('1f1cb8c3-dfab-4ed8-8d09-89f6ca4fb88c'),
    ("story", "sonnet"): uuid.UUID('04b97144-f0c5-4210-bbf2-1bd7031e3be8'),
    ("story", "opus"): uuid.UUID('e577fae2-7fdf-42d9-b5df-cf4bee4351ab'),
    ("story", "haiku"): uuid.UUID('778ad3c5-461f-4385-a27a-a55788e6abb8'),
}
_SECTION_ID_NAMESPACE = uuid.UUID('4ca1aa8d-9d58-4077-8f0e-521c5f524b83')

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE = "장면 헤더 판정 문안 채널 추가(활성 세트 사본)"

CHANNEL = "scene_judgment"
SCOPE = "story"

# 지시문 — 이번 턴 글만 보고 장소·시간을 짧게 적고, 근거가 없으면 비운다.
INSTRUCTION_BODY = (
    "[장면 판정]\n"
    "아래 [이번 턴]의 사용자 메시지와 진행자 응답만 읽고, 응답이 끝난 시점에 인물들이 있는 장면의 장소와 시간을 적는다.\n"
    "- place: 지금 있는 장소. 예) 학교 옥상, 민준의 자취방, 비 오는 버스 정류장\n"
    "- time: 지금의 때. 예) 방과 후, 새벽 두 시, 사흘 뒤 저녁\n"
    "- 각 칸은 24자 이내의 짧은 명사구로 쓴다. 문장으로 쓰지 않는다.\n"
    "- 이번 턴 글에 장소나 시간이 바뀌었거나 드러났다는 근거가 없으면 그 칸은 null 로 둔다. [직전 장면]이 그대로 이어진다.\n"
    "- 추측하거나 지어내지 않는다. 글에 쓰인 것만 옮긴다."
)

PREVIOUS_SCENE_BODY = "[직전 장면]\n장소: {previous_place}\n시간: {previous_time}"

TURN_CONTEXT_BODY = "[이번 턴]\n{user_label}: {user_message}\n{assistant_label}: {assistant_message}"

Row = tuple[str, str, str, str, str, bool, int]

# `(channel, scope, slot, variant, body, conditional, order)` — 새 채널은 기준 행이 없어 order 가 고정이다.
NEW_ROWS: tuple[Row, ...] = (
    (CHANNEL, SCOPE, "instruction", "", INSTRUCTION_BODY, False, 0),
    (CHANNEL, SCOPE, "previous_scene", "", PREVIOUS_SCENE_BODY, True, 1),
    (CHANNEL, SCOPE, "turn_context", "", TURN_CONTEXT_BODY, False, 2),
)

# 모델로 거르는 활성 규칙 — `load_active_prompt_set`(chat/prompt_builder.py)과 같다.
_ACTIVE_SET_SQL = sa.text(
    "SELECT id, user_label, story_assistant_label, story_example_label, character_assistant_label,"
    " published_at"
    " FROM prompt_sets WHERE status = 'published' AND lane = :lane AND model = :model"
    " ORDER BY published_at DESC LIMIT 1"
)
# 모델 열을 모르는 코드(옛 마이그레이션의 원시 SQL)의 활성 규칙.
_LANE_ONLY_ACTIVE_SET_SQL = sa.text(
    "SELECT id FROM prompt_sets WHERE status = 'published' AND lane = :lane ORDER BY published_at DESC LIMIT 1"
)
_SECTIONS_SQL = sa.text(
    'SELECT channel, scope, slot, variant, body, conditional, "order"'
    " FROM prompt_sections WHERE prompt_set_id = :id"
)
_DRAFT_SQL = sa.text("SELECT id FROM prompt_sets WHERE status = 'draft' AND lane = :lane AND model = :model")


def _gemini_seed_time(gemini_at: datetime, now: datetime) -> datetime:
    """새 Gemini 세트의 게시 시각 — 레인에서 가장 나중이 되게 `max(now, 원본 + 1초)`."""
    return max(now, gemini_at + timedelta(seconds=1))


def _seed_time(chain_at: datetime, gemini_seed_at: datetime) -> datetime:
    """Gemini 가 아닌 체인의 새 세트 게시 시각 — 그 체인 활성 시각과 새 Gemini 세트 시각의 중간값. 사이에 둘 시각이 없으면
    `RuntimeError`."""
    chosen = chain_at + (gemini_seed_at - chain_at) / 2
    if not chain_at < chosen < gemini_seed_at:
        raise RuntimeError(
            f"두 활성 조회 규칙을 함께 만족하는 게시 시각이 없다: 체인 활성 {chain_at}, 새 Gemini 세트 {gemini_seed_at}"
        )
    return chosen


def _section_id(
    lane: str, model: str, channel: str, scope: str, slot: str, variant: str, *, prefix: str = ""
) -> uuid.UUID:
    return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{prefix}{lane}:{model}:{channel}:{scope}:{slot}:{variant}")


def _rows_of(conn: Connection, set_id: uuid.UUID) -> list[Row]:
    return [tuple(row) for row in conn.execute(_SECTIONS_SQL, {"id": set_id}).fetchall()]


def _section_dicts(rows: Sequence[Row], *, model: str, set_id: uuid.UUID, prefix: str = "") -> list[dict[str, object]]:
    return [
        {
            "id": _section_id(LANE, model, channel, scope, slot, variant, prefix=prefix),
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


def _insert_set(
    conn: Connection,
    *,
    model: str,
    source: sa.Row[tuple[object, ...]],
    published_at: datetime,
    rows: Sequence[Row],
) -> None:
    set_id = NEW_SET_IDS[(LANE, model)]
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
                "lane": LANE,
                "model": model,
                "user_label": source.user_label,
                "story_assistant_label": source.story_assistant_label,
                "story_example_label": source.story_example_label,
                "character_assistant_label": source.character_assistant_label,
                "note": _NOTE,
                "published_at": published_at,
            }
        ],
    )
    conn.execute(sa.insert(prompt_sections_table), _section_dicts(rows, model=model, set_id=set_id))


def seed_published_sets(conn: Connection) -> None:
    """story 레인 네 체인에 새 세트를 넣고, 두 활성 조회 규칙으로 다시 확인한다.

    `op` 를 쓰지 않는다 — 테스트가 롤백되는 세션의 커넥션에 `run_sync` 로 부르기 위해서다."""
    existing = conn.execute(
        sa.select(sa.func.count()).select_from(prompt_sets_table).where(
            prompt_sets_table.c.id.in_(list(NEW_SET_IDS.values()))
        )
    ).scalar_one()
    if existing:
        raise RuntimeError(f"이 리비전의 세트가 이미 있다({existing}개)")
    sources = {model: conn.execute(_ACTIVE_SET_SQL, {"lane": LANE, "model": model}).one() for model in _MODELS}
    lane_only = conn.execute(_LANE_ONLY_ACTIVE_SET_SQL, {"lane": LANE}).one().id
    if lane_only != sources[_GEMINI].id:
        raise RuntimeError(
            f"[{LANE}] 레인만 보는 활성 조회가 이미 Gemini 세트가 아닌 {lane_only} 를 집는다 — 두 활성 조회 규칙을 함께"
            " 만족하는 게시 시각이 없다"
        )
    # 넣기 전에 네 체인을 모두 검사한다 — 하나라도 어긋나면 아무것도 넣지 않은 채 멈춘다.
    source_rows = {model: _rows_of(conn, sources[model].id) for model in _MODELS}
    for model in _MODELS:
        if any(row[0] == CHANNEL for row in source_rows[model]):
            raise RuntimeError(f"[{LANE}/{model}] {CHANNEL} 채널 행이 이미 있다")

    gemini_seed_at = _gemini_seed_time(sources[_GEMINI].published_at, datetime.now(UTC))
    for model in _MODELS:
        _insert_set(
            conn,
            model=model,
            source=sources[model],
            published_at=(
                gemini_seed_at if model == _GEMINI else _seed_time(sources[model].published_at, gemini_seed_at)
            ),
            rows=[*source_rows[model], *NEW_ROWS],
        )

    for model in _MODELS:
        chosen = conn.execute(_ACTIVE_SET_SQL, {"lane": LANE, "model": model}).one().id
        if chosen != NEW_SET_IDS[(LANE, model)]:
            raise RuntimeError(
                f"[{LANE}/{model}] 새 세트가 활성으로 뽑히지 않는다: 활성={chosen}, 새 세트={NEW_SET_IDS[(LANE, model)]}"
            )
    lane_only_after = conn.execute(_LANE_ONLY_ACTIVE_SET_SQL, {"lane": LANE}).one().id
    if lane_only_after != NEW_SET_IDS[(LANE, _GEMINI)]:
        raise RuntimeError(f"[{LANE}] 레인만 보는 활성 조회가 새 Gemini 세트를 집지 않는다: {lane_only_after}")


def _patch_drafts(conn: Connection) -> list[tuple[str, str]]:
    """story 레인 초안 중 이 채널 행이 없는 것에 새 행을 제자리에서 넣고, 넣은 (레인, 모델) 목록을 돌려준다. `op` 를 쓰지 않는
    이유는 `seed_published_sets` 와 같다."""
    patched: list[tuple[str, str]] = []
    for model in _MODELS:
        draft_id = conn.execute(_DRAFT_SQL, {"lane": LANE, "model": model}).scalar_one_or_none()
        if draft_id is None:
            continue
        if any(row[0] == CHANNEL for row in _rows_of(conn, draft_id)):
            continue
        conn.execute(sa.insert(prompt_sections_table), _section_dicts(NEW_ROWS, model=model, set_id=draft_id, prefix="draft:"))
        patched.append((LANE, model))
    return patched


def _delete_draft_rows(conn: Connection) -> list[tuple[str, str]]:
    """story 레인 초안의 이 채널 행을 지운다. 지운 (레인, 모델) 목록을 돌려준다."""
    found = conn.execute(
        sa.text(
            "SELECT DISTINCT p.id, p.model FROM prompt_sections s JOIN prompt_sets p ON p.id = s.prompt_set_id"
            " WHERE p.status = 'draft' AND p.lane = :lane AND s.channel = :channel ORDER BY p.model"
        ),
        {"lane": LANE, "channel": CHANNEL},
    ).fetchall()
    for draft_id, _model in found:
        conn.execute(
            sa.delete(prompt_sections_table).where(
                prompt_sections_table.c.prompt_set_id == draft_id, prompt_sections_table.c.channel == CHANNEL
            )
        )
    return [(LANE, model) for _id, model in found]


def upgrade() -> None:
    """Upgrade schema."""
    # 배포 중에도 떠 있는 API 가 prompt_sets 를 읽고 쓴다. 이 리비전은 행만 넣어 오래 쥐는 락이 없지만, 다른 트랜잭션 뒤에서
    # 끝없이 기다리지 않고 5초 안에 실패해 배포가 멈추게 첫 문장으로 건다.
    op.execute("SET LOCAL lock_timeout = '5s'")
    bind = op.get_bind()
    seed_published_sets(bind)
    _patch_drafts(bind)


def delete_seeded_rows(conn: Connection) -> None:
    """위 docstring 의 `downgrade()`. `op` 를 쓰지 않는 이유는 `seed_published_sets` 와 같다."""
    later: list[str] = []
    for (lane, model), seed_id in NEW_SET_IDS.items():
        count = conn.execute(
            sa.text(
                "SELECT count(*) FROM prompt_sets WHERE status = 'published' AND lane = :lane AND model = :model"
                " AND id <> :seed AND published_at > (SELECT published_at FROM prompt_sets WHERE id = :seed)"
            ),
            {"lane": lane, "model": model, "seed": seed_id},
        ).scalar_one()
        if count:
            later.append(f"{lane}/{model} {count}개")
    if later:
        raise RuntimeError(
            f"시드 뒤에 어드민이 게시한 세트가 있다({', '.join(later)}) — 되돌리면 장면 헤더 판정 행이 든 그 세트가 활성으로 남아"
            " 이전 코드의 그 체인 게시가 막힌다. 아무것도 지우지 않았다"
        )

    seed_ids = list(NEW_SET_IDS.values())
    conn.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.prompt_set_id.in_(seed_ids)))
    conn.execute(sa.delete(prompt_sets_table).where(prompt_sets_table.c.id.in_(seed_ids)))
    _delete_draft_rows(conn)


def downgrade() -> None:
    """Downgrade schema."""
    delete_seeded_rows(op.get_bind())
