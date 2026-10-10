"""상황 노트가 스토리 생성 프롬프트의 `[현재 상황]` 섹션에 실리는지 — 조건 평가(순수 함수)와 새 턴·편집·재생성·미리보기
경로를 본다.

조건은 생성 시점의 스탯 값(이번 턴 판정 반영 전)으로 평가한다. 재생성은 그 턴 판정이 이미 반영된 값으로 다시
평가하므로 원 생성과 다른 노트가 실릴 수 있다."""

import logging
import uuid
from collections.abc import AsyncIterator, Callable, Generator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import ImageMatchJudgmentResult, StatRuleJudgmentResult
from api.chat.room_stats import load_room_stats
from api.chat.turn_prompt import pick_situation_note_texts
from api.content.schemas import (
    EndingRuleDraftItem,
    EndingRuleGroupDraftItem,
    EndingRuleListDraftItem,
)
from api.db.models import ChatRoom, ChatRoomStat, Content, KeywordNote, SituationNote, StartingSetup, StatDef, StatRule
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.story import EndingRuleOperator, LogicalOp
from api.db.session import engine
from api.llm.client import LLMCallContext, LLMClient
from factories import (
    _add_situation_note,
    _clear_llm_override,
    _login_as,
    _make_user,
    _open_room,
    _override_llm_client,
    _story_with_setup,
)

_SECTION_HEADER = "[현재 상황]\n아래는 지금 이야기 세계에서 사실인 상황이다. 이번 장면은 이 사실과 어긋나지 않게 쓴다.\n"


def _rule(
    stat_id: uuid.UUID, operator: str, threshold: float, next_op: LogicalOp | None = None
) -> EndingRuleDraftItem:
    return EndingRuleDraftItem(
        id=uuid.uuid4(),
        stat_id=stat_id,
        operator=EndingRuleOperator(operator),
        threshold=threshold,
        next_op=next_op,
    )


def _group(rules: list[EndingRuleDraftItem], next_op: LogicalOp | None = None) -> EndingRuleGroupDraftItem:
    return EndingRuleGroupDraftItem(id=uuid.uuid4(), rules=rules, next_op=next_op)


# ── 조건 평가(순수 함수) ─────────────────────────────────────────────────────────────────────────

_A = uuid.uuid4()
_B = uuid.uuid4()
_MISSING = uuid.uuid4()
_STATS = {str(_A): 50.0, str(_B): 10.0}


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        pytest.param([_rule(_A, "gte", 50)], True, id="true"),
        pytest.param([_rule(_A, "gt", 50)], False, id="false"),
        pytest.param([_rule(_MISSING, "lte", 100)], False, id="missing-stat-is-false-for-any-operator"),
        pytest.param([_rule(_A, "gte", 0, LogicalOp.AND), _rule(_B, "gte", 20)], False, id="and"),
        pytest.param([_rule(_A, "gte", 99, LogicalOp.OR), _rule(_B, "eq", 10)], True, id="or"),
        # 좌에서 우로 차례로 묶는다 — (참 or 거짓) and 거짓 = 거짓. 우선순위로 묶으면 참이 된다.
        pytest.param(
            [_rule(_A, "eq", 50, LogicalOp.OR), _rule(_B, "gt", 10, LogicalOp.AND), _rule(_B, "lt", 10)],
            False,
            id="and-or-left-to-right",
        ),
        pytest.param(
            [_rule(_A, "lt", 0, LogicalOp.OR), _group([_rule(_A, "eq", 50, LogicalOp.AND), _rule(_B, "lte", 10)])],
            True,
            id="group",
        ),
        pytest.param(
            [_group([_rule(_A, "eq", 50, LogicalOp.AND), _rule(_MISSING, "gte", 0)])], False, id="group-missing-stat"
        ),
    ],
)
def test_situation_note_condition_evaluation(rules: list[EndingRuleListDraftItem], expected: bool) -> None:
    assert pick_situation_note_texts([(rules, "본문")], _STATS) == (["본문"] if expected else [])


@pytest.mark.parametrize(
    "rules",
    [pytest.param([], id="no-rules"), pytest.param([_group([])], id="only-empty-group")],
)
def test_note_without_any_rule_is_never_loaded(rules: list[EndingRuleListDraftItem]) -> None:
    """평가기는 빈 목록을 참으로 보지만, 조건 없는 노트가 매 턴 실리면 안 된다 — 발행이 거절하는 노트와 같은 기준."""
    assert pick_situation_note_texts([(rules, "조건 없음")], _STATS) == []


def test_true_notes_keep_the_given_order() -> None:
    notes: list[tuple[list[EndingRuleListDraftItem], str]] = [
        ([_rule(_A, "gte", 0)], "첫째"),
        ([_rule(_A, "lt", 0)], "거짓"),
        ([], "조건 없음"),
        ([_rule(_B, "lte", 10)], "셋째"),
    ]
    assert pick_situation_note_texts(notes, _STATS) == ["첫째", "셋째"]


# ── 실채팅 ─────────────────────────────────────────────────────────────────────────────────────


class _RecordingLLMClient(LLMClient):
    """생성 프롬프트를 남긴다. 스탯 판정은 `fired` 의 규칙 id 목록을 차례로 꺼내 답하고(다 쓰면 "발동한 규칙 없음"), 칸
    판정은 없음."""

    def __init__(self, fired: list[list[str]] | None = None) -> None:
        self.fired = list(fired or [])
        self.generation_prompts: list[str] = []
        self.judgment_schemas: list[Any] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.generation_prompts.append(prompt)
        yield "응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.judgment_schemas.append(response_schema)
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=self.fired.pop(0) if self.fired else [])
        if response_schema is ImageMatchJudgmentResult:
            return ImageMatchJudgmentResult(matched_image_entity_id=None)
        raise AssertionError(f"예상하지 못한 판정 호출: {response_schema.__name__}")


def _add_stat(db_session: AsyncSession, setup: StartingSetup, name: str, initial_value: int) -> uuid.UUID:
    """스탯 하나와 그 규칙 하나(폭 +30). 규칙이 있어야 스탯 판정이 불린다."""
    entity_id = uuid.uuid4()
    stat_def_id = uuid.uuid4()
    db_session.add(
        StatDef(
            id=stat_def_id,
            entity_id=entity_id,
            starting_setup_id=setup.id,
            name=name,
            icon="heart",
            color="#ff0000",
            min_value=0,
            max_value=100,
            initial_value=initial_value,
            unit=None,
            description=name,
            order=1,
        )
    )
    db_session.add(StatRule(entity_id=uuid.uuid4(), stat_def_id=stat_def_id, condition=f"{name} 조건", delta=30, order=0))
    return entity_id


async def _logged_in_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, user_id: uuid.UUID, content: Content, setup: StartingSetup
) -> uuid.UUID:
    await db_session.commit()
    await _login_as(db_client, user_id)
    resp = await db_client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)}
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def _set_room_stat(db_session: AsyncSession, room_id: uuid.UUID, stat_id: uuid.UUID, value: int) -> None:
    await db_session.execute(
        update(ChatRoomStat)
        .where(ChatRoomStat.chat_room_id == room_id, ChatRoomStat.stat_entity_id == stat_id)
        .values(current_value=Decimal(value))
    )
    await db_session.commit()


async def _post(db_client: httpx.AsyncClient, fake: LLMClient, url: str, body: dict[str, object] | None = None) -> None:
    _override_llm_client(fake)
    try:
        resp = await db_client.post(url, json=body) if body is not None else await db_client.post(url)
    finally:
        _clear_llm_override()
    assert resp.status_code == 200, resp.text


def _section(prompt: str) -> str | None:
    """`[현재 상황]` 섹션의 노트 줄. 섹션이 없으면 None."""
    if _SECTION_HEADER not in prompt:
        return None
    return prompt.split(_SECTION_HEADER, 1)[1].split("\n\n", 1)[0]


async def test_send_loads_true_notes_in_order_right_after_keyword_notes(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    trust = _add_stat(db_session, setup, "신뢰", 50)
    days = _add_stat(db_session, setup, "남은 날", 5)
    # 순서의 역순으로 넣는다 — 넣은 순서가 곧 순서면 정렬이 빠져도 같은 결과가 나온다.
    _add_situation_note(db_session, setup, "표지-둘째", [_rule(days, "lte", 0)], order=2)
    await db_session.flush()
    _add_situation_note(db_session, setup, "표지-조건 없음", [], order=3)
    await db_session.flush()
    _add_situation_note(db_session, setup, "표지-거짓", [_rule(trust, "gte", 90)], order=1)
    await db_session.flush()
    _add_situation_note(db_session, setup, "표지-첫째", [_rule(trust, "gte", 70)], order=0)
    assert content.current_published_version_id is not None
    db_session.add(
        KeywordNote(
            entity_id=uuid.uuid4(),
            content_version_id=content.current_published_version_id,
            starting_setup_id=None,
            info_text="표지-키워드 노트",
            trigger_keywords=[],
            order=0,
            exclude_keywords=[],
            sticky_turns=0,
            always_on=True,
        )
    )
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    await _set_room_stat(db_session, room_id, trust, 80)
    await _set_room_stat(db_session, room_id, days, 0)
    fake = _RecordingLLMClient()

    await _post(db_client, fake, f"/chat-rooms/{room_id}/messages", {"content": "안녕"})

    [prompt] = fake.generation_prompts
    assert _section(prompt) == "표지-첫째\n표지-둘째"
    keyword_at = prompt.index("[키워드북]")
    section_at = prompt.index(_SECTION_HEADER)
    assert keyword_at < section_at < prompt.index("안녕", section_at)


async def test_note_with_stat_at_initial_value_when_room_has_no_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    days = _add_stat(db_session, setup, "남은 날", 5)
    _add_situation_note(db_session, setup, "표지-마감 주간", [_rule(days, "lte", 7)])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    await db_session.execute(sa.delete(ChatRoomStat).where(ChatRoomStat.chat_room_id == room_id))
    await db_session.commit()
    fake = _RecordingLLMClient()

    await _post(db_client, fake, f"/chat-rooms/{room_id}/messages", {"content": "안녕"})

    assert _section(fake.generation_prompts[0]) == "표지-마감 주간"


async def test_section_is_dropped_when_no_note_is_true(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    trust = _add_stat(db_session, setup, "신뢰", 50)
    _add_situation_note(db_session, setup, "표지-거짓", [_rule(trust, "gte", 90)])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    fake = _RecordingLLMClient()

    await _post(db_client, fake, f"/chat-rooms/{room_id}/messages", {"content": "안녕"})

    assert "[현재 상황]" not in fake.generation_prompts[0]


async def test_send_evaluates_before_judgment_and_regenerate_reevaluates_with_current_values(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """원 생성은 보낸 순간의 값(50)으로 거짓이고, 그 턴 판정이 80 으로 올린 뒤의 재생성은 참이다 — 재생성 때 화면
    게이지와 맞는 노트가 실린다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    trust = _add_stat(db_session, setup, "신뢰", 50)
    _add_situation_note(db_session, setup, "표지-가까워짐", [_rule(trust, "gte", 70)])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    fake = _RecordingLLMClient([["a1"]])

    await _post(db_client, fake, f"/chat-rooms/{room_id}/messages", {"content": "손을 잡는다"})
    await _post(db_client, fake, f"/chat-rooms/{room_id}/regenerate")

    original, regenerated = fake.generation_prompts
    assert _section(original) is None
    assert _section(regenerated) == "표지-가까워짐"
    # 재생성은 생성 프롬프트를 지금 값(80)으로 조립한 뒤에야 그 턴의 스탯을 되돌려 다시 판정한다 — 그래서 판정이 두 번이어도
    # 재생성 프롬프트의 노트는 지금 값의 것이다.
    assert fake.judgment_schemas == [StatRuleJudgmentResult, StatRuleJudgmentResult]


async def test_edit_evaluates_notes_with_current_values(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    trust = _add_stat(db_session, setup, "신뢰", 50)
    _add_situation_note(db_session, setup, "표지-가까워짐", [_rule(trust, "gte", 70)])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    fake = _RecordingLLMClient()
    await _post(db_client, fake, f"/chat-rooms/{room_id}/messages", {"content": "안녕"})
    await _set_room_stat(db_session, room_id, trust, 75)
    user_message = await db_session.scalar(
        select(ChatMessage).where(ChatMessage.chat_room_id == room_id, ChatMessage.role == ChatMessageRole.USER)
    )
    assert user_message is not None

    _override_llm_client(fake)
    try:
        resp = await db_client.patch(f"/chat-rooms/{room_id}/messages/{user_message.id}", json={"content": "다시"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200, resp.text
    first, edited = fake.generation_prompts
    assert _section(first) is None
    assert _section(edited) == "표지-가까워짐"


async def test_second_stat_read_in_a_request_sees_value_committed_by_another_request(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """노트가 있는 방은 생성 프롬프트 조립 때 스탯 행을 읽고, 판정 단계가 스트리밍 뒤에 다시 읽는다. 그 사이 같은 방의
    다른 요청이 커밋한 값(50 → 55)을 두 번째 읽기가 봐야 판정이 그 변화를 덮어쓰지 않는다. 첫 읽기의 행 객체를 붙들어
    둔다 — 객체가 세션에 살아 있을 때만 옛 값이 남는다. 돌아오는 행은 같은 객체여야 판정의 쓰기가 세션에 잡힌다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    trust = _add_stat(db_session, setup, "신뢰", 50)
    _add_situation_note(db_session, setup, "표지-노트", [_rule(trust, "gte", 0)])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)

    _, first_rows, first_stats = await load_room_stats(db_session, room_id, setup.id)
    assert first_stats[str(trust)] == 50.0
    async with AsyncSession(bind=db_session.bind, expire_on_commit=False) as other_request:
        await _set_room_stat(other_request, room_id, trust, 55)
    _, second_rows, second_stats = await load_room_stats(db_session, room_id, setup.id)

    assert second_stats[str(trust)] == 55.0
    assert second_rows[str(trust)] is first_rows[str(trust)]


async def test_notes_keep_loading_after_ending_reached(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """엔딩 뒤에는 판정이 멈춰 스탯이 동결되지만 노트 평가는 그 값으로 계속한다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    days = _add_stat(db_session, setup, "남은 날", 5)
    _add_situation_note(db_session, setup, "표지-당일", [_rule(days, "lte", 0)])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    await _set_room_stat(db_session, room_id, days, 0)
    await db_session.execute(update(ChatRoom).where(ChatRoom.id == room_id).values(ending_reached=True))
    await db_session.commit()
    fake = _RecordingLLMClient()

    await _post(db_client, fake, f"/chat-rooms/{room_id}/messages", {"content": "그 뒤로"})

    assert _section(fake.generation_prompts[0]) == "표지-당일"
    assert StatRuleJudgmentResult not in fake.judgment_schemas


async def test_broken_condition_json_skips_only_that_note_and_completes_the_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    trust = _add_stat(db_session, setup, "신뢰", 50)
    db_session.add(
        SituationNote(
            entity_id=uuid.uuid4(),
            starting_setup_id=setup.id,
            name="손으로 고친 노트",
            info_text="표지-깨진 노트",
            order=0,
            condition_rules=[{"kind": "모르는 꼴"}],
        )
    )
    _add_situation_note(db_session, setup, "표지-멀쩡한 노트", [_rule(trust, "gte", 0)], order=1)
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    fake = _RecordingLLMClient()

    with caplog.at_level(logging.WARNING, logger="api.chat.turn_prompt"):
        await _post(db_client, fake, f"/chat-rooms/{room_id}/messages", {"content": "안녕"})

    assert _section(fake.generation_prompts[0]) == "표지-멀쩡한 노트"
    assert any("상황 노트" in r.getMessage() for r in caplog.records)


@contextmanager
def _stat_table_reads() -> Generator[Callable[[], int], None, None]:
    """스탯 정의·방 스탯 테이블을 읽는 SQL 문 개수."""
    count = 0

    def _before_cursor_execute(_conn: object, _cursor: object, statement: str, *_args: object) -> None:
        nonlocal count
        if "FROM stat_defs" in statement or "FROM chat_room_stats" in statement:
            count += 1

    sa.event.listen(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield lambda: count
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)


@pytest.mark.parametrize(("with_note", "expected_reads"), [(False, 0), (True, 2)])
async def test_stats_are_read_for_the_prompt_only_when_the_setup_has_notes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, with_note: bool, expected_reads: int
) -> None:
    """엔딩 뒤라 판정 단계는 스탯을 읽지 않는다 — 남는 읽기는 생성 프롬프트 조립 몫이다. 노트가 없는 시작설정은 그
    읽기가 0 이라 노트 기능 이전과 쿼리 수가 같다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="문이 열린다.")
    trust = _add_stat(db_session, setup, "신뢰", 50)
    if with_note:
        _add_situation_note(db_session, setup, "표지-노트", [_rule(trust, "gte", 0)])
    room_id = await _logged_in_room(db_client, db_session, user_id, content, setup)
    await db_session.execute(update(ChatRoom).where(ChatRoom.id == room_id).values(ending_reached=True))
    await db_session.commit()
    fake = _RecordingLLMClient()

    with _stat_table_reads() as reads:
        await _post(db_client, fake, f"/chat-rooms/{room_id}/messages", {"content": "안녕"})

    assert reads() == expected_reads
    assert (_section(fake.generation_prompts[0]) is not None) is with_note


async def test_character_chat_has_no_situation_section_and_reads_no_stats(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=0)
    fake = _RecordingLLMClient()

    with _stat_table_reads() as reads:
        await _post(db_client, fake, f"/chat-rooms/{room.room_id}/messages", {"content": "안녕"})

    assert "[현재 상황]" not in fake.generation_prompts[0]
    assert reads() == 0


# ── 미리보기 ──────────────────────────────────────────────────────────────────────────────────


def _payload_rule(stat_id: str, operator: str, threshold: float) -> dict[str, object]:
    return {"kind": "rule", "id": str(uuid.uuid4()), "statId": stat_id, "operator": operator, "threshold": threshold, "nextOp": None}


async def test_preview_evaluates_notes_with_session_stats(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """첫 턴은 세션 시작값(50)으로, 둘째 턴은 첫 턴 판정이 올린 값(90)으로 평가한다. 조건 없는 노트는 실리지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    stat_id = str(uuid.uuid4())
    setup = {
        "id": str(uuid.uuid4()),
        "name": "시작설정1",
        "prologue": "프롤로그",
        "openingMessage": None,
        "playguide": None,
        "suggestedReplies": [],
        "statDefs": [
            {
                "id": stat_id,
                "name": "신뢰",
                "icon": "heart",
                "color": "rose",
                "minValue": 0,
                "maxValue": 100,
                "initialValue": 50,
                "unit": None,
                "description": "신뢰",
                "rules": [{"id": str(uuid.uuid4()), "condition": "가까워진다", "delta": 40}],
            }
        ],
        "endings": [],
        "situationNotes": [
            {"id": str(uuid.uuid4()), "name": "가까움", "infoText": "표지-가까움", "conditionRules": [_payload_rule(stat_id, "gte", 80)]},
            {"id": str(uuid.uuid4()), "name": "조건 없음", "infoText": "표지-조건 없음", "conditionRules": []},
            {"id": str(uuid.uuid4()), "name": "보통", "infoText": "표지-보통", "conditionRules": [_payload_rule(stat_id, "gte", 50)]},
        ],
    }
    payload = {
        "name": "잃어버린 도시",
        "oneLiner": "한 줄 소개",
        "thumbnailAssetId": None,
        "promptTemplate": "basic",
        "settingText": "세계관 설명",
        "developmentExample": None,
        "customPrompt": None,
        "startingSetups": [setup],
        "keywordNotes": [],
        "shortcuts": [],
        "description": "상세 설명",
        "genreId": None,
        "target": None,
        "hashtags": [],
        "visibility": "private",
    }
    created = await db_client.post("/preview-sessions", json=payload)
    assert created.status_code == 201, created.text
    session_id = created.json()["previewSessionId"]
    fake = _RecordingLLMClient([["a1"]])

    for text in ["안녕", "그래서"]:
        await _post(db_client, fake, f"/preview-sessions/{session_id}/messages", {"content": text})

    first, second = fake.generation_prompts
    assert _section(first) == "표지-보통"
    assert _section(second) == "표지-가까움\n표지-보통"
