"""prompt sections summary secret marking slot

Revision ID: 0aeadefcf159
Revises: e4e407a62d03
Create Date: 2026-10-16 14:00:00.000000

요약 호출 채널(`memory_summary`)에 비밀 표기 슬롯(`secret_marking`, conditional) 하나를 더한다. 요약 모델이 비밀을 적을 때
아는 인물 표기 `(이름·이름만 앎)` 를 붙이고, 비밀 내용을 표기 없는 다른 문장에 다시 쓰지 않게 하는 지시다. 본문은
자리표시자 `{room_people}`(그 방의 인물 이름 목록) 하나를 받는다.

**값이 비면 섹션째 빠진다**(`render_prompt_channel` 의 conditional 규칙). 코드는 요약 비밀 표기 스위치
(`memory_summary_secret_marking`)가 켜졌을 때만 값을 채우므로, 꺼진 동안 요약 프롬프트는 이 리비전 전과 바이트까지 같다.
켜졌는데 이름이 0개면 코드가 고정 문구를 값으로 넣어 슬롯이 늘 실린다.

**위치**: 요약 지시문(`instruction`) **바로 뒤**, 사용자 이름 한 줄(`user_name`) 앞. 문안을 고른 측정이 이 자리에서 렌더했다.
절대 order 가 아니라 지시문 행의 현재 order 로 자리 `X = 지시문 order + 1` 을 정하고, 그 채널의 `order >= X` 를 +1 한 뒤 새 행을
`X` 에 둔다. 나머지 행의 상대 순서는 그대로다.

**심는 것**: story·character 레인마다 네 체인(gemini·sonnet·opus·haiku)에 새 published 세트 하나씩, 모두 여덟. 요약 채널은 네
체인 모두에 있다 — 요약 모델 설정이 어느 체인을 고르든 그 세트에 슬롯이 있어야 한다. 여덟 체인의 새 행은 같은 본문이다.

**새 세트는 그 체인 활성 세트의 바이트 사본에 이 행 하나를 더하고 요약 채널의 뒤 행 order 를 민 것이다** — 라벨·다른 모든 행
(운영자가 어드민에서 고친 문안 — 운영 story 요약 지시문이 그렇다 — 과 얼려 둔 소설 행 포함)의 본문과 conditional 이 그대로
옮겨진다. **게시된 세트는 고치지 않는다.**

**가정 검사는 본문이 아니라 슬롯 모양으로 한다.** 요약 지시문은 운영에서 어드민이 고쳐 게시해 마이그레이션 원본과 다르므로
본문을 견주면 늘 멈춘다. 대신 활성 세트의 요약 채널 행을 order 순으로 늘어놓은 (scope, slot, variant) 목록이
`SUMMARY_LAYOUT_BEFORE` 와 정확히 같아야 한다(order 가 겹치면 순서가 정해지지 않아 어긋난 것으로 본다). 어긋나면 — 이 슬롯이
이미 있거나, 행이 빠졌거나 더 있거나, 어드민이 순서를 바꿨으면 — `RuntimeError` 로 배포를 멈춘다. 한 레인의 네 체인을 모두
검사한 뒤에 넣는다(체인이 한 트랜잭션이라 앞 리비전까지 함께 롤백된다).

**`published_at` — 두 활성 조회 규칙을 함께 만족시킨다**(앞의 기억 문안 리비전들과 같은 규칙).
- 레인만 보는 조회(모델 열을 모르는 원시 SQL)는 레인의 최신 게시본을 고른다 — 새 Gemini 세트는 파이썬 `max(now, 원본 + 1초)`.
- 모델로 거르는 조회(`load_active_prompt_set`)는 (레인, 모델)마다 최신 게시본을 고른다 — sonnet·opus·haiku 의 새 세트는 (그 체인
  활성 시각, 그 레인 새 Gemini 세트 시각)의 **중간값**. 사이에 둘 시각이 없으면 `RuntimeError`.
- 삽입 뒤 두 규칙으로 다시 SELECT 해 확인한다. 어긋나면 `RuntimeError`.
- 그 밖에 멈추는 경우: 이 리비전의 세트가 이미 있을 때, 레인만 보는 조회가 이미 Gemini 가 아닌 세트를 집을 때.

**초안**: 초안의 요약 채널이 같은 모양이면 그 자리에 같은 행을 **제자리에서** 넣고 order 를 민다(기존 행의 body 는 건드리지
않는다). 모양이 다르면(운영자가 고치던 중이면) 그대로 둔다 — 초안 하나 때문에 배포를 멈출 일은 아니다. 그대로 둔 초안은 새
코드의 게시 검증(슬롯 집합 "누락")에 막히므로 어드민에서 지금 활성본을 불러 다시 고쳐야 한다.

**PK**: 세트는 리터럴 UUID(`NEW_SET_IDS`), 섹션은 새 namespace 의 `uuid5("{lane}:{model}:{channel}:{scope}:{slot}:{variant}")`,
초안 행은 같은 이름 앞에 `draft:` 를 붙인다. `version` 은 전 레인·전 모델 published 최대 + 1 을 (story, character) × (gemini,
sonnet, opus, haiku) 순서로 매긴다(어드민 게시와 같은 규칙).

**옛 이미지가 이 데이터 위에서 도는 구간**(배포 중 겹침, 이미지만 되돌린 동안): 옛 코드는 `room_people` 값을 넘기지 않아 새 행이
conditional 로 빠지고 렌더가 깨지지 않는다 — 요약 프롬프트는 이 리비전 전과 같다. 다만 옛 코드의 게시 검증이 새 세트를
"잉여"로 거부해 **여덟 체인의 어드민 게시만** 막힌다.

⚠️ **운영 메모**:
- body 에서 `{room_people}` 을 지우면 드롭 조건이 거짓이 되어 **스위치가 꺼진 방에도 이 지시가 실린다**. 게시 검증은 "허용 밖
  이름"만 막고 "필수 이름의 존재"는 보지 않는다.
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 배포 직후 최대 300초 동안 옛 세트로 렌더한다. 스위치가 켜져 있어도 그동안은
  슬롯이 없을 뿐 렌더는 깨지지 않는다.
- 배포 전부터 열어 둔 어드민 프롬프트 편집 탭에서 저장하면 초안이 새 행을 잃고 게시가 슬롯 집합 검사("누락")로 막힌다.
  **배포 뒤에는 편집 탭을 새로고침한다.**
- 🔴 **시드를 손으로 지우지 않는다.** 되돌리려면 아래 `downgrade` 를 쓴다.

**롤백 순서**: 1순위는 이미지만 되돌리기다(위 옛 이미지 구간 — 렌더는 그대로, 어드민 게시만 막힘). 게시까지 되살려야 하면
**이 리비전 파일이 있는 이미지로** `downgrade` 를 실행한 뒤 이미지를 되돌린다.

`downgrade()`(`delete_seeded_rows`): 시드 뒤에 어드민이 여덟 체인 중 하나에 새 버전을 게시했으면 아무것도 지우지 않고
`RuntimeError` 로 멈춘다 — 되돌리면 그 게시본이 활성으로 남아 되돌린 뜻이 사라지고, 무엇을 버릴지는 사람이 정해야 한다. 없으면
리터럴 시드의 섹션 → 세트를 지우고(이전 활성 세트는 처음부터 이 행이 없다), 초안의 이 행을 지운 뒤 그 채널의 뒤 행을 −1 한다
(PK 가 아니라 레인·모델·slot 으로 찾는다 — 초안 저장이 섹션을 통째로 갈아 PK 가 바뀌어 있을 수 있다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트(`tests/test_summary_secret_marking_prompt_migration.py`)가 이 모듈을
`importlib` 로 불러 `seed_published_sets`·`_patch_drafts`·`delete_seeded_rows`·`_delete_draft_rows` 를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0aeadefcf159'
down_revision: str | Sequence[str] | None = 'e4e407a62d03'
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

_LANES: tuple[str, ...] = ("story", "character")
_GEMINI = "gemini"
# 요약 채널이 있는 네 체인. Gemini 가 맨 앞이어야 한다(다른 체인의 게시 시각이 새 Gemini 세트 시각에 기댄다).
_MODELS: tuple[str, ...] = (_GEMINI, "sonnet", "opus", "haiku")

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_IDS: dict[tuple[str, str], uuid.UUID] = {
    ("story", "gemini"): uuid.UUID('be004e14-83dc-4af1-b7ad-c2479224cacf'),
    ("story", "sonnet"): uuid.UUID('3a971dd7-bd19-4dee-842b-3d1e70ae175e'),
    ("story", "opus"): uuid.UUID('146de98d-fa34-439a-83c2-d592ceb04ab7'),
    ("story", "haiku"): uuid.UUID('2122eff0-a1ab-41c7-b394-7a15ac6fb8cc'),
    ("character", "gemini"): uuid.UUID('16b9db76-f283-4a63-b940-9f8092e3410c'),
    ("character", "sonnet"): uuid.UUID('e6ed1305-1888-4377-a7d5-a08bb34d7415'),
    ("character", "opus"): uuid.UUID('752f216a-a138-4a98-aa4e-f6020b7c65b7'),
    ("character", "haiku"): uuid.UUID('16f27451-9669-43fa-9c65-15919c19ad11'),
}
_SECTION_ID_NAMESPACE = uuid.UUID('e8eb96ac-ba97-4fc4-881e-0816840ea5d2')

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE = "요약 비밀 표기 슬롯 추가(활성 세트 사본)"

SUMMARY_CHANNEL = "memory_summary"
SCOPE = "both"
SLOT = "secret_marking"
ANCHOR_SLOT = "instruction"

# 이 리비전 이전 요약 채널의 모양 — order 순 (scope, slot, variant).
SUMMARY_LAYOUT_BEFORE: tuple[tuple[str, str, str], ...] = (
    ("both", "instruction", ""),
    ("both", "user_name", ""),
    ("both", "previous_summary", ""),
    ("both", "turn_context", ""),
)

# 요약 비밀 표기 슬롯 — 측정에서 고른 판을 바이트 그대로 옮겼다. 자리표시자는 `{room_people}` 하나다.
SECRET_MARKING_BODY = (
    "[비밀 표기]\n"
    "- 이 이야기의 인물 이름: {room_people}. 아는 사람을 적을 때 이 이름 꼴을 그대로 쓴다.\n"
    "- 비밀은 한 인물이 몇 사람에게만 털어놓은 일, \"비밀로 해 달라\"고 한 일, 남몰래 숨긴 일, 혼자 본 일이다. 여럿이 함께 있는"
    " 자리에서 드러난 일은 비밀이 아니다.\n"
    "- 비밀을 적는 문장 끝에는 아는 사람 표기를 괄호로 붙인다: (이름·이름만 앎). 털어놓은 사람과 들은 사람을 모두 적고, 들은 사람이"
    " 사용자면 사용자도 적는다.\n"
    "- 비밀 내용은 표기가 붙은 그 문장에만 쓴다. [지금]·[지난 일]이나 다른 문장에 그 비밀 내용을 표기 없이 다시 쓰지 않는다.\n"
    "- [직전 요약]에 표기와 함께 적힌 비밀은 표기까지 그대로 옮긴다."
)

Row = tuple[str, str, str, str, str, bool, int]

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


def _layout_problem(rows: Sequence[Row]) -> str | None:
    """요약 채널이 이 리비전 이전 모양이 아니면 그 설명, 맞으면 None."""
    summary = sorted(
        (order, scope, slot, variant)
        for channel, scope, slot, variant, _b, _c, order in rows
        if channel == SUMMARY_CHANNEL
    )
    orders = [order for order, *_ in summary]
    layout = tuple((scope, slot, variant) for _, scope, slot, variant in summary)
    if layout == SUMMARY_LAYOUT_BEFORE and len(set(orders)) == len(orders):
        return None
    actual = ", ".join(
        f"{slot}{'/' + variant if variant else ''}({scope})={order}" for order, scope, slot, variant in summary
    )
    return f"{SUMMARY_CHANNEL} 채널의 슬롯 모양이 이 리비전 이전 기대와 다르다: {actual or '(행 없음)'}"


def _insert_order(rows: Sequence[Row]) -> int:
    """새 행의 자리 — 요약 지시문 행의 현재 order + 1."""
    anchor = [order for channel, _s, slot, _v, _b, _c, order in rows if (channel, slot) == (SUMMARY_CHANNEL, ANCHOR_SLOT)]
    return anchor[0] + 1


def _with_new_row(rows: Sequence[Row]) -> list[Row]:
    """기존 행 그대로(요약 채널의 자리 이상 행만 order +1), 그리고 새 행."""
    at = _insert_order(rows)
    shifted: list[Row] = [
        (channel, scope, slot, variant, body, cond, order + 1 if channel == SUMMARY_CHANNEL and order >= at else order)
        for channel, scope, slot, variant, body, cond, order in rows
    ]
    return [*shifted, (SUMMARY_CHANNEL, SCOPE, SLOT, "", SECRET_MARKING_BODY, True, at)]


def _gemini_seed_time(gemini_at: datetime, now: datetime) -> datetime:
    """새 Gemini 세트의 게시 시각 — 레인에서 가장 나중이 되게 `max(now, 원본 + 1초)`."""
    return max(now, gemini_at + timedelta(seconds=1))


def _seed_time(chain_at: datetime, gemini_seed_at: datetime) -> datetime:
    """Gemini 가 아닌 체인의 새 세트 게시 시각 — 그 체인 활성 시각과 그 레인 새 Gemini 세트 시각의 중간값. 사이에 둘 시각이
    없으면 `RuntimeError`."""
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


def _insert_set(
    conn: Connection,
    *,
    lane: str,
    model: str,
    source: sa.Row[tuple[object, ...]],
    published_at: datetime,
    rows: Sequence[Row],
) -> None:
    set_id = NEW_SET_IDS[(lane, model)]
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
    conn.execute(
        sa.insert(prompt_sections_table),
        [
            {
                "id": _section_id(lane, model, channel, scope, slot, variant),
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


def seed_published_sets(conn: Connection) -> None:
    """레인마다 네 체인에 새 세트를 넣고, 두 활성 조회 규칙으로 다시 확인한다.

    `op` 를 쓰지 않는다 — 테스트가 롤백되는 세션의 커넥션에 `run_sync` 로 부르기 위해서다."""
    existing = conn.execute(
        sa.select(sa.func.count()).select_from(prompt_sets_table).where(
            prompt_sets_table.c.id.in_(list(NEW_SET_IDS.values()))
        )
    ).scalar_one()
    if existing:
        raise RuntimeError(f"이 리비전의 세트가 이미 있다({existing}개)")
    for lane in _LANES:
        sources = {model: conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": model}).one() for model in _MODELS}
        lane_only = conn.execute(_LANE_ONLY_ACTIVE_SET_SQL, {"lane": lane}).one().id
        if lane_only != sources[_GEMINI].id:
            raise RuntimeError(
                f"[{lane}] 레인만 보는 활성 조회가 이미 Gemini 세트가 아닌 {lane_only} 를 집는다 — 두 활성 조회 규칙을 함께"
                " 만족하는 게시 시각이 없다"
            )
        # 넣기 전에 네 체인을 모두 검사한다 — 하나라도 어긋나면 그 레인에는 아무것도 넣지 않은 채 멈춘다.
        source_rows = {model: _rows_of(conn, sources[model].id) for model in _MODELS}
        for model in _MODELS:
            problem = _layout_problem(source_rows[model])
            if problem is not None:
                raise RuntimeError(f"[{lane}/{model}] {problem}")

        gemini_seed_at = _gemini_seed_time(sources[_GEMINI].published_at, datetime.now(UTC))
        for model in _MODELS:
            _insert_set(
                conn,
                lane=lane,
                model=model,
                source=sources[model],
                published_at=(
                    gemini_seed_at if model == _GEMINI else _seed_time(sources[model].published_at, gemini_seed_at)
                ),
                rows=_with_new_row(source_rows[model]),
            )

        for model in _MODELS:
            chosen = conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": model}).one().id
            if chosen != NEW_SET_IDS[(lane, model)]:
                raise RuntimeError(
                    f"[{lane}/{model}] 새 세트가 활성으로 뽑히지 않는다: 활성={chosen}, 새 세트={NEW_SET_IDS[(lane, model)]}"
                )
        lane_only_after = conn.execute(_LANE_ONLY_ACTIVE_SET_SQL, {"lane": lane}).one().id
        if lane_only_after != NEW_SET_IDS[(lane, _GEMINI)]:
            raise RuntimeError(f"[{lane}] 레인만 보는 활성 조회가 새 Gemini 세트를 집지 않는다: {lane_only_after}")


def _patch_drafts(conn: Connection) -> list[tuple[str, str]]:
    """요약 채널이 이 리비전 이전 모양인 초안에 새 행을 제자리에서 넣고(뒤 행 order +1, body 불변), 넣은 (레인, 모델) 목록을
    돌려준다. 모양이 다른 초안은 그대로 둔다(위 docstring). `op` 를 쓰지 않는 이유는 `seed_published_sets` 와 같다."""
    patched: list[tuple[str, str]] = []
    for lane in _LANES:
        for model in _MODELS:
            draft_id = conn.execute(_DRAFT_SQL, {"lane": lane, "model": model}).scalar_one_or_none()
            if draft_id is None:
                continue
            rows = _rows_of(conn, draft_id)
            if _layout_problem(rows) is not None:
                continue
            at = _insert_order(rows)
            conn.execute(
                sa.text(
                    'UPDATE prompt_sections SET "order" = "order" + 1'
                    ' WHERE prompt_set_id = :id AND channel = :channel AND "order" >= :at'
                ),
                {"id": draft_id, "channel": SUMMARY_CHANNEL, "at": at},
            )
            conn.execute(
                sa.insert(prompt_sections_table),
                [
                    {
                        "id": _section_id(lane, model, SUMMARY_CHANNEL, SCOPE, SLOT, "", prefix="draft:"),
                        "prompt_set_id": draft_id,
                        "channel": SUMMARY_CHANNEL,
                        "scope": SCOPE,
                        "slot": SLOT,
                        "variant": "",
                        "body": SECRET_MARKING_BODY,
                        "conditional": True,
                        "order": at,
                    }
                ],
            )
            patched.append((lane, model))
    return patched


def _delete_draft_rows(conn: Connection) -> list[tuple[str, str]]:
    """초안의 이 슬롯 행을 지우고 그 채널의 뒤 행을 −1 한다. 지운 (레인, 모델) 목록을 돌려준다."""
    found = conn.execute(
        sa.text(
            'SELECT s.id, s.prompt_set_id, s."order", p.lane, p.model FROM prompt_sections s'
            " JOIN prompt_sets p ON p.id = s.prompt_set_id"
            " WHERE p.status = 'draft' AND p.lane IN ('story', 'character') AND s.channel = :channel AND s.slot = :slot"
            " ORDER BY p.lane DESC, p.model"
        ),
        {"channel": SUMMARY_CHANNEL, "slot": SLOT},
    ).fetchall()
    deleted: list[tuple[str, str]] = []
    for section_id, prompt_set_id, order, lane, model in found:
        conn.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.id == section_id))
        conn.execute(
            sa.text(
                'UPDATE prompt_sections SET "order" = "order" - 1'
                ' WHERE prompt_set_id = :id AND channel = :channel AND "order" > :x'
            ),
            {"id": prompt_set_id, "channel": SUMMARY_CHANNEL, "x": order},
        )
        deleted.append((lane, model))
    return deleted


def upgrade() -> None:
    """Upgrade schema."""
    # 배포 중에도 떠 있는 API 가 prompt_sets 를 읽고 쓴다. 이 리비전은 행만 넣고 초안 몇 행만 고쳐 오래 쥐는 락이 없지만, 다른
    # 트랜잭션 뒤에서 끝없이 기다리지 않고 5초 안에 실패해 배포가 멈추게 첫 문장으로 건다.
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
            f"시드 뒤에 어드민이 게시한 세트가 있다({', '.join(later)}) — 되돌려도 그 세트가 활성으로 남는다. 아무것도 지우지"
            " 않았다"
        )

    seed_ids = list(NEW_SET_IDS.values())
    conn.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.prompt_set_id.in_(seed_ids)))
    conn.execute(sa.delete(prompt_sets_table).where(prompt_sets_table.c.id.in_(seed_ids)))
    _delete_draft_rows(conn)


def downgrade() -> None:
    """Downgrade schema."""
    delete_seeded_rows(op.get_bind())
