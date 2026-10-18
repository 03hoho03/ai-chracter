"""prompt sections summary secret marking source rule

Revision ID: 0c1a85bc5c2f
Revises: 6fbf1e9a65b8
Create Date: 2026-10-19 14:00:00.000000

요약 채널(`memory_summary`)의 비밀 표기 슬롯(`secret_marking`) 본문 끝에 한 항목을 더한다 — 아직 확인되지 않은 주장을 요약에
적을 때 그 주장이 누구에게서 나왔는지를 함께 적게 하는 규칙이다. 앞 판의 다섯 항목은 글자 하나 바뀌지 않고, 그 뒤에 줄바꿈과 새
항목 한 줄이 붙는다. 자리표시자는 앞 판과 같은 `{room_people}` 하나다.

**운영 효과가 없다**: 이 슬롯은 conditional 이고, 코드는 요약 비밀 표기 스위치(`memory_summary_secret_marking`)가 켜졌을 때만
`room_people` 값을 채운다. 꺼진 동안 값이 비어 슬롯이 섹션째 빠지므로 요약 프롬프트는 이 리비전 전과 바이트까지 같다 — 요약
결과도, 그 요약을 읽는 엔딩 판정·생성 프롬프트도 바뀌지 않는다. 스위치를 켜면 새 항목까지 실린다.

**심는 것**: story·character 레인마다 네 체인(gemini·sonnet·opus·haiku)에 새 published 세트 하나씩, 모두 여덟. 비밀 표기 슬롯은
여덟 체인 모두에 있다 — 요약 모델 설정이 어느 체인을 고르든 그 세트의 본문이 바뀌어야 한다.

**새 세트는 그 체인 활성 세트의 바이트 사본에서 비밀 표기 슬롯 본문 하나만 바꾼 것이다** — 라벨·다른 모든 행(운영자가 어드민에서
고친 문안 — 운영 story 요약 지시문(`memory_summary`/`instruction`)이 그렇다 —, 얼려 둔 소설 행, 기억 추출 지시문, 장면 헤더 판정
행 포함)과 conditional·order 가 그대로 옮겨진다. 행을 더하거나 빼지 않는다. **요약 지시문은 검사하지도 바꾸지도 않는다.**
**게시된 세트는 고치지 않는다.**

**슬롯 본문은 활성 본문이 그 슬롯을 만든 리비전 `0aeadefcf159` 의 문안(`OLD_SECRET_MARKING_BODY`)과 바이트로 같을 때만 바꾼다.**
그 뒤 이 슬롯을 바꾼 리비전은 없다. 다르면 어드민이 고쳐 게시한 운영 문안이라 조용히 덮어쓰지 않고 `RuntimeError` 로 배포를
멈춘다 — 사람이 고친 문안과 새 문안을 합칠지 판단해야 한다.

**`published_at` — 두 활성 조회 규칙을 함께 만족시킨다**(앞의 기억 문안 리비전들과 같은 규칙).
- 레인만 보는 조회(모델 열을 모르는 원시 SQL)는 레인의 최신 게시본을 고른다 — 새 Gemini 세트는 파이썬 `max(now, 원본 + 1초)`.
- 모델로 거르는 조회(`load_active_prompt_set`)는 (레인, 모델)마다 최신 게시본을 고른다 — sonnet·opus·haiku 의 새 세트는 (그 체인
  활성 시각, 그 레인 새 Gemini 세트 시각)의 **중간값**. 사이에 둘 시각이 없으면 `RuntimeError`.
- 삽입 뒤 두 규칙으로 다시 SELECT 해 확인한다. 어긋나면 `RuntimeError`.

**가정이 어긋나면 배포를 멈춘다**(`RuntimeError`, 체인이 한 트랜잭션이라 앞 리비전까지 함께 롤백된다): 이 리비전의 세트가 이미
있을 때, 레인만 보는 조회가 이미 Gemini 가 아닌 세트를 집을 때, 활성 세트에 `memory_summary` 의 `secret_marking` 행이 정확히
하나가 아닐 때, 그 본문이 앞 리비전 문안과 다를 때. 한 레인의 네 체인을 모두 검사한 뒤에 넣는다.

**초안**: 초안은 슬롯 본문이 앞 리비전 문안과 같을 때만 새 문안으로 바꾸고, 다르면(행이 없거나 운영자가 고치던 중이면) 그대로
둔다 — 초안은 고치던 작업이라 덮어쓰면 그 작업이 사라지고, 초안 하나 때문에 배포를 멈출 일도 아니다. 행 모양과 자리표시자가
바뀌지 않아 초안의 게시 검증에는 영향이 없다.

**PK**: 세트는 리터럴 UUID(`NEW_SET_IDS`), 섹션은 새 namespace 의 `uuid5("{lane}:{model}:{channel}:{scope}:{slot}:{variant}")`.
`version` 은 전 레인·전 모델 published 최대 + 1 을 (story, character) × (gemini, sonnet, opus, haiku) 순서로 매긴다(어드민 게시와
같은 규칙).

**옛 이미지가 이 데이터 위에서 도는 구간**(배포 중 겹침, 이미지만 되돌린 동안): 슬롯·자리표시자·행 집합이 앞 리비전과 같고 본문
글만 바뀌므로 옛 코드도 그대로 렌더하고(스위치가 꺼져 있으면 슬롯이 빠지는 것까지 같다), 옛 코드의 어드민 게시 검증도 새 세트를
통과시킨다.

⚠️ **운영 메모**:
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 스위치를 켜 둔 환경은 배포 직후 최대 300초 동안 옛 본문으로 렌더할 수 있다.
- body 에서 `{room_people}` 을 지우면 드롭 조건이 거짓이 되어 **스위치가 꺼진 방에도 이 지시가 실린다**. 게시 검증은 "허용 밖
  이름"만 막고 "필수 이름의 존재"는 보지 않는다.
- 🔴 **시드를 손으로 지우지 않는다.** 되돌리려면 아래 `downgrade` 를 쓴다.
- 🔴 **프롬프트 옛 버전을 통째로 복원하지 않는다** — 현재 활성본에서 바뀐 섹션만 고친다.

**롤백 순서**: 이 리비전은 문안만 바꾸고 코드는 바꾸지 않는다. 옛 본문으로 되돌려야 하면 **이 리비전 파일이 있는 이미지로**
`downgrade` 를 실행한다 — 이미지만 되돌리면 새 본문이 남은 채 옛 코드가 돈다(렌더는 문제없고 스위치를 켠 요약은 계속 새 문안이다).

`downgrade()`(`delete_seeded_rows`): 시드 뒤에 어드민이 여덟 체인 중 하나에 새 버전을 게시했으면 아무것도 지우지 않고
`RuntimeError` 로 멈춘다 — 되돌리면 그 게시본이 활성으로 남아 되돌린 뜻이 사라지고, 무엇을 버릴지는 사람이 정해야 한다. 없으면
리터럴 시드의 섹션 → 세트를 지운다 — 이전 활성 세트는 처음부터 옛 본문을 갖고 있다. 초안은 슬롯 본문이 이 리비전의 새 문안과
같으면 옛 문안으로 되돌린다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트(`tests/test_summary_secret_marking_source_prompt_migration.py`)가 이
모듈을 `importlib` 로 불러 `seed_published_sets`·`_patch_drafts`·`delete_seeded_rows`·`_delete_draft_rows` 를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0c1a85bc5c2f'
down_revision: str | Sequence[str] | None = '6fbf1e9a65b8'
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
# 비밀 표기 슬롯이 있는 네 체인. Gemini 가 맨 앞이어야 한다(다른 체인의 게시 시각이 새 Gemini 세트 시각에 기댄다).
_MODELS: tuple[str, ...] = (_GEMINI, "sonnet", "opus", "haiku")

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_IDS: dict[tuple[str, str], uuid.UUID] = {
    ("story", "gemini"): uuid.UUID('c8162bc5-b1ad-44f7-8e29-9df7d5fd7d3b'),
    ("story", "sonnet"): uuid.UUID('f50649ea-7239-4fcf-8a8e-6bad42bebade'),
    ("story", "opus"): uuid.UUID('c9e4dfd6-8708-48a7-9412-b6bc1557e288'),
    ("story", "haiku"): uuid.UUID('59249913-6446-4574-b1ca-797d03bd753e'),
    ("character", "gemini"): uuid.UUID('5e51b6a4-6c18-4a45-a0f4-6d8d50b683a2'),
    ("character", "sonnet"): uuid.UUID('e26f5370-03ec-46f1-b57c-b7841a38c5dd'),
    ("character", "opus"): uuid.UUID('6b83b747-42fa-4c60-94bb-e928640f95a4'),
    ("character", "haiku"): uuid.UUID('10fda22d-7da9-4810-b3b3-f5a800b82b78'),
}
_SECTION_ID_NAMESPACE = uuid.UUID('d802c5bd-ba18-441c-b1a0-c659b5a5dc8d')

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE = "요약 비밀 표기 슬롯에 미확인 주장의 출처 규칙 추가(활성 세트 사본)"

SUMMARY_CHANNEL = "memory_summary"
SECRET_MARKING_SLOT = "secret_marking"

# 비밀 표기 슬롯 새 판 — 측정에서 고른 판을 바이트 그대로 옮겼다(측정이 이 슬롯 자리에 넣은 글 그대로, 끝 줄바꿈 없음). 앞 판
# 전체 뒤에 줄바꿈과 항목 한 줄을 더한 것이다. 자리표시자는 `{room_people}` 하나다.
SECRET_MARKING_BODY = (
    "[비밀 표기]\n"
    "- 이 이야기의 인물 이름: {room_people}. 아는 사람을 적을 때 이 이름 꼴을 그대로 쓴다.\n"
    "- 비밀은 한 인물이 몇 사람에게만 털어놓은 일, \"비밀로 해 달라\"고 한 일, 남몰래 숨긴 일, 혼자 본 일이다. 여럿이 함께 있는"
    " 자리에서 드러난 일은 비밀이 아니다.\n"
    "- 비밀을 적는 문장 끝에는 아는 사람 표기를 괄호로 붙인다: (이름·이름만 앎). 털어놓은 사람과 들은 사람을 모두 적고, 들은 사람이"
    " 사용자면 사용자도 적는다.\n"
    "- 비밀 내용은 표기가 붙은 그 문장에만 쓴다. [지금]·[지난 일]이나 다른 문장에 그 비밀 내용을 표기 없이 다시 쓰지 않는다.\n"
    "- [직전 요약]에 표기와 함께 적힌 비밀은 표기까지 그대로 옮긴다.\n"
    "- 확인 안 된 주장은 일어난 일처럼 쓰지 않는다. 인물이 말로만 한 것(지난 일, 그 자리에 없는 사람의 일, 사용자에"
    " 대한 말, 소문)은 말한 사람을 붙여 \"<이름>이 ~라고 말했다\"로 쓴다. 진행자 서술이나 사용자 지문으로 일어난"
    " 일만 말한 사람 없이 쓴다."
)

# 이 슬롯을 만든 리비전(`0aeadefcf159`)의 문안 — 그 뒤 이 슬롯을 바꾼 리비전이 없어 활성 본문은 이것이어야 한다.
OLD_SECRET_MARKING_BODY = (
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
_SWAP_BODY_SQL = sa.text(
    "UPDATE prompt_sections SET body = :to_body"
    " WHERE prompt_set_id = :id AND channel = :channel AND slot = :slot AND body = :from_body"
)


def _assert_slot_row(rows: Sequence[Row], *, what: str) -> None:
    """게시본에 비밀 표기 슬롯 행이 정확히 하나이고 그 본문이 앞 리비전 문안과 바이트로 같은지 본다. 어긋나면 `RuntimeError` —
    `what` 은 메시지에 쓸 세트 이름이다. 요약 지시문은 보지 않는다(운영 story 지시문은 어드민이 고친 판이다)."""
    matches = [row for row in rows if row[0] == SUMMARY_CHANNEL and row[2] == SECRET_MARKING_SLOT]
    if len(matches) != 1:
        raise RuntimeError(
            f"[{what}] {SUMMARY_CHANNEL} 채널의 {SECRET_MARKING_SLOT} 행이 정확히 하나가 아니다({len(matches)}개)"
        )
    if matches[0][4] != OLD_SECRET_MARKING_BODY:
        raise RuntimeError(
            f"[{what}] {SUMMARY_CHANNEL} 채널의 {SECRET_MARKING_SLOT} 본문이 앞 리비전이 심은 문안과 다르다 — 어드민이 고친"
            " 운영 문안을 덮어쓰지 않는다. 고친 문안과 새 문안을 합친 뒤 다시 배포한다"
        )


def _with_new_slot(rows: Sequence[Row]) -> list[Row]:
    """기존 행 그대로, 비밀 표기 슬롯 본문만 새 문안."""
    return [
        (
            channel,
            scope,
            slot,
            variant,
            SECRET_MARKING_BODY if (channel, slot) == (SUMMARY_CHANNEL, SECRET_MARKING_SLOT) else body,
            cond,
            order,
        )
        for channel, scope, slot, variant, body, cond, order in rows
    ]


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


def _section_id(lane: str, model: str, channel: str, scope: str, slot: str, variant: str) -> uuid.UUID:
    return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{lane}:{model}:{channel}:{scope}:{slot}:{variant}")


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
            _assert_slot_row(source_rows[model], what=f"{lane}/{model}")

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
                rows=_with_new_slot(source_rows[model]),
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


def _swap_draft_slot(conn: Connection, *, from_body: str, to_body: str) -> list[tuple[str, str]]:
    """초안의 비밀 표기 슬롯 본문이 `from_body` 와 같으면 `to_body` 로 바꾸고, 바꾼 (레인, 모델) 목록을 돌려준다."""
    swapped: list[tuple[str, str]] = []
    for lane in _LANES:
        for model in _MODELS:
            draft_id = conn.execute(_DRAFT_SQL, {"lane": lane, "model": model}).scalar_one_or_none()
            if draft_id is None:
                continue
            result = conn.execute(
                _SWAP_BODY_SQL,
                {
                    "id": draft_id,
                    "channel": SUMMARY_CHANNEL,
                    "slot": SECRET_MARKING_SLOT,
                    "from_body": from_body,
                    "to_body": to_body,
                },
            )
            if result.rowcount:
                swapped.append((lane, model))
    return swapped


def _patch_drafts(conn: Connection) -> list[tuple[str, str]]:
    """초안의 비밀 표기 슬롯 본문이 앞 리비전 문안과 같으면 새 문안으로 바꾼다(위 docstring). `op` 를 쓰지 않는 이유는
    `seed_published_sets` 와 같다."""
    return _swap_draft_slot(conn, from_body=OLD_SECRET_MARKING_BODY, to_body=SECRET_MARKING_BODY)


def _delete_draft_rows(conn: Connection) -> list[tuple[str, str]]:
    """초안의 비밀 표기 슬롯 본문이 이 리비전의 새 문안이면 옛 문안으로 되돌린다."""
    return _swap_draft_slot(conn, from_body=SECRET_MARKING_BODY, to_body=OLD_SECRET_MARKING_BODY)


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
