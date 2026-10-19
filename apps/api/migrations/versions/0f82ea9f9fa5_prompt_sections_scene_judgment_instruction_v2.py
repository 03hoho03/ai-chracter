"""prompt sections scene judgment instruction v2

Revision ID: 0f82ea9f9fa5
Revises: 0c1a85bc5c2f
Create Date: 2026-10-19 00:29:45.872739

장면 헤더 판정 지시문(`scene_judgment`/`instruction`)을 새 판으로 바꾼다. 사람이 검수한 측정에서 앞 판은 세 가지로 틀렸다 — 약속이나
회상으로 말만 나온 장소·때를 지금 장면으로 읽었고, 한 턴에 두 장소가 섞이면 새 장소로 옮겨 적었고, 글에 없는 시각을 지어냈다. 새
판은 그 셋을 막는 지시를 더했다(말로만 나온 장소·시간은 적지 않는다, 옮겨 갔다고 글이 분명히 말할 때만 새 장소를 적는다, 시각을
짐작해 만들지 않는다). 직전 장면·이번 턴 두 행은 그대로다.

**효과가 바로 난다**: 장면 판정은 장면 헤더를 켠 스토리 방의 매 턴 응답 뒤에 돌므로, 이 리비전이 적용된 뒤의 다음 판정부터 새
문안으로 렌더된다. 생성 프롬프트에는 이 채널이 실리지 않으므로 생성 쪽 바이트는 바뀌지 않는다.

**심는 것**: story 레인 네 체인(gemini·sonnet·opus·haiku)에 새 published 세트 하나씩, 모두 넷. 판정은 스탯 판정 모델 설정으로
체인을 고르므로 그 설정이 어느 체인을 고르든 그 세트의 문안이 바뀌어야 한다. character 레인에는 이 채널이 없다.

**새 세트는 그 체인 활성 세트의 바이트 사본에서 장면 판정 지시문 하나만 바꾼 것이다** — 라벨·다른 모든 행(운영자가 어드민에서
고친 문안, 얼려 둔 소설 행 포함)과 order 가 그대로 옮겨진다. 행을 더하거나 빼지 않는다. **게시된 세트는 고치지 않는다.**

**지시문은 활성 본문이 그 채널을 심은 리비전 `0346abdbcc92` 의 문안(`OLD_INSTRUCTION_BODY`)과 바이트로 같을 때만 바꾼다.** 다르면
어드민이 고쳐 게시한 운영 문안이라 조용히 덮어쓰지 않고 `RuntimeError` 로 배포를 멈춘다 — 사람이 고친 문안과 새 문안을 합칠지
판단해야 한다(앞의 회상·사실 추출 지시문 리비전과 같은 규칙). 그 뒤 story 레인에 세트를 게시한 리비전 셋 — 장면 추출 지시문
(`eb8d3cc6d5c2`), 사실 추출 지시문 차례(`c1f3945cb802`), 요약 비밀 표기 출처(`0c1a85bc5c2f`) — 은 모두 이 행을 바이트 그대로
옮겼으므로 비교 기준은 여전히 `0346abdbcc92` 의 문안이다. 아래에서 "앞 리비전 문안"은 이 문안을 가리킨다.

**`published_at` — 두 활성 조회 규칙을 함께 만족시킨다**(앞의 판정·요약 문안 리비전들과 같은 규칙).
- 레인만 보는 조회(모델 열을 모르는 원시 SQL)는 레인의 최신 게시본을 고른다 — 새 Gemini 세트는 파이썬 `max(now, 원본 + 1초)`.
- 모델로 거르는 조회(`load_active_prompt_set`)는 (레인, 모델)마다 최신 게시본을 고른다 — sonnet·opus·haiku 의 새 세트는 (그 체인
  활성 시각, 새 Gemini 세트 시각)의 **중간값**. 사이에 둘 시각이 없으면 `RuntimeError`.
- 삽입 뒤 두 규칙으로 다시 SELECT 해 확인한다. 어긋나면 `RuntimeError`.

**가정이 어긋나면 배포를 멈춘다**(`RuntimeError`, 체인이 한 트랜잭션이라 앞 리비전까지 함께 롤백된다): 이 리비전의 세트가 이미
있을 때, 레인만 보는 조회가 이미 Gemini 가 아닌 세트를 집을 때, 활성 세트에 `scene_judgment` 의 `instruction` 행이 정확히 하나가
아닐 때, 그 본문이 앞 리비전 문안과 다를 때. 네 체인을 모두 검사한 뒤에 넣는다.

**초안**: 초안은 지시문이 앞 리비전 문안과 같을 때만 새 문안으로 바꾸고, 다르면(행이 없거나 운영자가 고치던 중이면) 그대로 둔다
— 초안은 고치던 작업이라 덮어쓰면 그 작업이 사라지고, 초안 하나 때문에 배포를 멈출 일도 아니다. 행 모양은 바뀌지 않아 초안의
게시 검증에는 영향이 없다.

**PK**: 세트는 리터럴 UUID(`NEW_SET_IDS`), 섹션은 새 namespace 의 `uuid5("{lane}:{model}:{channel}:{scope}:{slot}:{variant}")`.
`version` 은 전 레인·전 모델 published 최대 + 1 을 gemini·sonnet·opus·haiku 순서로 매긴다(어드민 게시와 같은 규칙).

**옛 이미지가 이 데이터 위에서 도는 구간**(배포 중 겹침, 이미지만 되돌린 동안): 슬롯·자리표시자·행 집합이 앞 리비전과 같고(두
지시문 모두 자리표시자가 없다) 본문 글만 바뀌므로 옛 코드도 그대로 렌더하고, 옛 코드의 어드민 게시 검증도 새 세트를 통과시킨다.
그 구간에 옛 이미지가 돌린 장면 판정도 새 문안을 쓴다.

⚠️ **운영 메모**:
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 배포 직후 최대 300초 동안 옛 세트(옛 지시문)로 판정할 수 있다.
- 🔴 **시드를 손으로 지우지 않는다.** 되돌리려면 아래 `downgrade` 를 쓴다.
- 🔴 **프롬프트 옛 버전을 통째로 복원하지 않는다** — 현재 활성본에서 바뀐 섹션만 고친다.

**롤백 순서**: 이미지만 되돌리면 새 지시문이 남은 채 옛 코드가 돈다(렌더는 문제없지만 판정은 계속 새 문안이다). 옛 지시문까지
되돌려야 하면 **이 리비전 파일이 있는 이미지로** `downgrade` 를 실행한다.

`downgrade()`(`delete_seeded_rows`): 시드 뒤에 어드민이 네 체인 중 하나에 새 버전을 게시했으면 아무것도 지우지 않고
`RuntimeError` 로 멈춘다 — 되돌리면 그 게시본이 활성으로 남아 되돌린 뜻이 사라지고, 무엇을 버릴지는 사람이 정해야 한다. 없으면
리터럴 시드의 섹션 → 세트를 지운다 — 이전 활성 세트는 처음부터 옛 지시문을 갖고 있다. 초안은 지시문이 이 리비전의 새 문안과
같으면 옛 문안으로 되돌린다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트(`tests/test_scene_judgment_instruction_v2_migration.py`)가 이 모듈을
`importlib` 로 불러 `seed_published_sets`·`_patch_drafts`·`delete_seeded_rows`·`_delete_draft_rows` 를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0f82ea9f9fa5'
down_revision: str | Sequence[str] | None = '0c1a85bc5c2f'
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
# 장면 판정 채널이 있는 네 체인. Gemini 가 맨 앞이어야 한다(다른 체인의 게시 시각이 새 Gemini 세트 시각에 기댄다).
_MODELS: tuple[str, ...] = (_GEMINI, "sonnet", "opus", "haiku")

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_IDS: dict[tuple[str, str], uuid.UUID] = {
    ("story", "gemini"): uuid.UUID('8be829e3-2f42-4960-aca3-1368758f3fd5'),
    ("story", "sonnet"): uuid.UUID('8820d9ef-e092-4970-9bb1-09c1aac1877c'),
    ("story", "opus"): uuid.UUID('23bf4c08-f30c-480b-a068-1f3321ce8e23'),
    ("story", "haiku"): uuid.UUID('5e5cadb2-41e7-4f4d-8f17-8230ea38aaed'),
}
_SECTION_ID_NAMESPACE = uuid.UUID('0f247202-1a32-488d-8651-ca934fcefe40')

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE = "장면 헤더 판정 지시문을 약속·회상·장소 섞임·지어낸 시각을 막는 판으로 교체(활성 세트 사본)"

CHANNEL = "scene_judgment"
SCOPE = "story"
_INSTRUCTION_SLOT = "instruction"

# 장면 판정 지시문 새 판 — 약속·계획·회상·통화로 말만 나온 장소·시간을 적지 않고, 두 장소가 함께 나오면 옮겨 갔다고 글이 분명히
# 말할 때만 새 장소를 적고, 시각을 짐작해 만들지 않게 하는 지시를 더했다. 자리표시자가 없다.
INSTRUCTION_BODY = (
    "[장면 판정]\n"
    "아래 [이번 턴]의 사용자 메시지와 진행자 응답만 읽고, 응답이 끝난 시점에 인물들이 실제로 있는 장소와 시간을 적는다.\n"
    "- place: 지금 있는 장소. 예) 학교 옥상, 민준의 자취방, 비 오는 버스 정류장\n"
    "- time: 지금의 때. 예) 방과 후, 새벽 두 시, 사흘 뒤 저녁\n"
    "- 각 칸은 24자 이내의 짧은 명사구로 쓴다. 문장으로 쓰지 않는다.\n"
    "- 약속·계획·회상·전화·문자로 말만 나온 장소와 시간은 지금 장면이 아니다. 적지 않는다.\n"
    "- 이동하는 중이거나 두 장소가 함께 나오면, 인물이 다른 곳으로 옮겨 갔다고 글이 분명히 말할 때만 새 장소를 적고 아니면 null 로 둔다.\n"
    "- 시간은 글에 쓰였거나 분명히 드러난 것만 적는다. 정확한 시각을 짐작해 만들지 않는다.\n"
    "- 이번 턴 글에 장소나 시간이 바뀌었거나 드러났다는 근거가 없으면 그 칸은 null 로 둔다. [직전 장면]이 그대로 이어진다.\n"
    "- 추측하거나 지어내지 않는다. 글에 쓰인 것만 옮긴다."
)

# 장면 판정 채널을 심은 리비전 `0346abdbcc92` 의 지시문(그 뒤 리비전들은 이 행을 바이트 그대로 옮겼다) — 활성 본문이 이것과
# 바이트로 같을 때만 바꾼다. 이 파일은 다른 리비전을 import 하지 않으므로 다시 적는다(테스트가 그 리비전 상수와 같은지 본다).
OLD_INSTRUCTION_BODY = (
    "[장면 판정]\n"
    "아래 [이번 턴]의 사용자 메시지와 진행자 응답만 읽고, 응답이 끝난 시점에 인물들이 있는 장면의 장소와 시간을 적는다.\n"
    "- place: 지금 있는 장소. 예) 학교 옥상, 민준의 자취방, 비 오는 버스 정류장\n"
    "- time: 지금의 때. 예) 방과 후, 새벽 두 시, 사흘 뒤 저녁\n"
    "- 각 칸은 24자 이내의 짧은 명사구로 쓴다. 문장으로 쓰지 않는다.\n"
    "- 이번 턴 글에 장소나 시간이 바뀌었거나 드러났다는 근거가 없으면 그 칸은 null 로 둔다. [직전 장면]이 그대로 이어진다.\n"
    "- 추측하거나 지어내지 않는다. 글에 쓰인 것만 옮긴다."
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
_SWAP_BODY_SQL = sa.text(
    "UPDATE prompt_sections SET body = :to_body"
    " WHERE prompt_set_id = :id AND channel = :channel AND slot = :slot AND body = :from_body"
)


def _assert_instruction_row(rows: Sequence[Row], *, what: str) -> None:
    """게시본에 지시문 행이 정확히 하나이고 그 본문이 앞 리비전 문안과 바이트로 같은지 본다. 어긋나면 `RuntimeError` — `what` 은
    메시지에 쓸 세트 이름이다."""
    matches = [row for row in rows if row[0] == CHANNEL and row[2] == _INSTRUCTION_SLOT]
    if len(matches) != 1:
        raise RuntimeError(f"[{what}] {CHANNEL} 채널의 {_INSTRUCTION_SLOT} 행이 정확히 하나가 아니다({len(matches)}개)")
    if matches[0][4] != OLD_INSTRUCTION_BODY:
        raise RuntimeError(
            f"[{what}] {CHANNEL} 채널의 {_INSTRUCTION_SLOT} 본문이 앞 리비전이 심은 문안과 다르다 — 어드민이 고친 운영 문안을"
            " 덮어쓰지 않는다. 고친 문안과 새 문안을 합친 뒤 다시 배포한다"
        )


def _with_new_instruction(rows: Sequence[Row]) -> list[Row]:
    """기존 행 그대로, 장면 판정 지시문만 새 문안."""
    return [
        (
            channel,
            scope,
            slot,
            variant,
            INSTRUCTION_BODY if (channel, slot) == (CHANNEL, _INSTRUCTION_SLOT) else body,
            cond,
            order,
        )
        for channel, scope, slot, variant, body, cond, order in rows
    ]


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


def _section_id(lane: str, model: str, channel: str, scope: str, slot: str, variant: str) -> uuid.UUID:
    return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{lane}:{model}:{channel}:{scope}:{slot}:{variant}")


def _rows_of(conn: Connection, set_id: uuid.UUID) -> list[Row]:
    return [tuple(row) for row in conn.execute(_SECTIONS_SQL, {"id": set_id}).fetchall()]


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
    conn.execute(
        sa.insert(prompt_sections_table),
        [
            {
                "id": _section_id(LANE, model, channel, scope, slot, variant),
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
        _assert_instruction_row(source_rows[model], what=f"{LANE}/{model}")

    gemini_seed_at = _gemini_seed_time(sources[_GEMINI].published_at, datetime.now(UTC))
    for model in _MODELS:
        _insert_set(
            conn,
            model=model,
            source=sources[model],
            published_at=(
                gemini_seed_at if model == _GEMINI else _seed_time(sources[model].published_at, gemini_seed_at)
            ),
            rows=_with_new_instruction(source_rows[model]),
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


def _swap_draft_instruction(conn: Connection, *, from_body: str, to_body: str) -> list[tuple[str, str]]:
    """story 레인 초안에서 장면 판정 지시문이 `from_body` 와 같으면 `to_body` 로 바꾸고, 바꾼 (레인, 모델) 목록을 돌려준다."""
    swapped: list[tuple[str, str]] = []
    for model in _MODELS:
        draft_id = conn.execute(_DRAFT_SQL, {"lane": LANE, "model": model}).scalar_one_or_none()
        if draft_id is None:
            continue
        result = conn.execute(
            _SWAP_BODY_SQL,
            {
                "id": draft_id,
                "channel": CHANNEL,
                "slot": _INSTRUCTION_SLOT,
                "from_body": from_body,
                "to_body": to_body,
            },
        )
        if result.rowcount:
            swapped.append((LANE, model))
    return swapped


def _patch_drafts(conn: Connection) -> list[tuple[str, str]]:
    """초안의 지시문이 앞 리비전 문안과 같으면 새 문안으로 바꾼다(위 docstring). `op` 를 쓰지 않는 이유는
    `seed_published_sets` 와 같다."""
    return _swap_draft_instruction(conn, from_body=OLD_INSTRUCTION_BODY, to_body=INSTRUCTION_BODY)


def _delete_draft_rows(conn: Connection) -> list[tuple[str, str]]:
    """초안의 지시문이 이 리비전의 새 문안이면 옛 문안으로 되돌린다."""
    return _swap_draft_instruction(conn, from_body=INSTRUCTION_BODY, to_body=OLD_INSTRUCTION_BODY)


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
