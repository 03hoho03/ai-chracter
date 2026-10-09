import inspect
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic_core import PydanticSerializationError
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import router as chat_router
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    StatRuleJudgmentResult,
)
from api.chat.preview_session import get_preview_session
from api.chat.schemas import PreviewSessionState
from api.core.rate_limit_gate import enforce_chat_rate_limit
from api.db.models.chat import ChatMessageRole, ChatRoom
from api.db.models.persona import UserPersona
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, LLMPolicyViolationError
from factories import (
    ENDING_PRIORITY_SCENARIOS,
    EndingPriorityScenario,
    _clear_llm_override,
    _login_as,
    _make_user,
    _override_llm_client,
    _parse_sse_events,
    _read_golden_prompt,
    ending_priority_marker,
    ending_priority_stat_rules,
    judged_ending_names,
)


def _character_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "아리아",
        "oneLiner": "한 줄 소개",
        "thumbnailAssetId": None,
        "intro": "안녕하세요, 아리아예요",
        "exampleDialogues": [],
        "characterPrompt": "너는 아리아다.",
        "playguide": None,
        "situationalImages": [],
        "description": "상세 설명",
        "genreId": None,
        "target": None,
        "hashtags": [],
        "visibility": "private",
    }
    payload.update(overrides)
    return payload


def _story_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "잃어버린 도시",
        "oneLiner": "한 줄 소개",
        "thumbnailAssetId": None,
        "promptTemplate": "basic",
        "settingText": "세계관 설명",
        "developmentExample": None,
        "customPrompt": None,
        "startingSetups": [],
        "keywordNotes": [],
        "shortcuts": [],
        "description": "상세 설명",
        "genreId": None,
        "target": None,
        "hashtags": [],
        "visibility": "private",
    }
    payload.update(overrides)
    return payload


def _starting_setup_item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "name": "시작설정1",
        "prologue": "프롤로그",
        "openingMessage": None,
        "playguide": None,
        "suggestedReplies": [],
        "statDefs": [],
        "endings": [],
    }
    item.update(overrides)
    return item


def _stat_def_item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "name": "체력",
        "icon": "heart",
        "color": "rose",
        "minValue": 0,
        "maxValue": 100,
        "initialValue": 50,
        "unit": None,
        "description": "체력 스탯",
        # 규칙 하나(a1, +30). 규칙이 있어야 스탯 판정이 불린다 — 발동시키면 초기값 50 이 80 이 된다.
        "rules": [{"id": str(uuid.uuid4()), "condition": "체력이 오르는 일이 일어난다", "delta": 30}],
    }
    item.update(overrides)
    return item


def _ending_item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "name": "해피엔딩",
        "turnCountGate": 1,
        "judgmentPrompt": "행복한 결말에 도달했는가",
        "epilogue": "모두가 행복하게 살았다.",
        "hint": None,
        "statRules": [],
    }
    item.update(overrides)
    return item


class _FakeLLMClient(LLMClient):
    """호출 순서대로 소비되는 구조화 응답 큐 + 마지막 생성 프롬프트 캡처 —
    test_chat_ending_pipeline_api.py의 큐 기반 fake와 동일한 모양."""

    def __init__(
        self,
        tokens: list[str],
        structured_results: list[Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.tokens = tokens
        self._structured_results = list(structured_results or [])
        self.generate_structured_calls: list[Any] = []
        self.structured_prompts: list[str] = []
        self.received_prompt: str | None = None
        self.received_system_instruction: str | None = None
        self.error = error
        self.usages: list[LLMCallContext] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.usages.append(usage)
        self.received_prompt = prompt
        self.received_system_instruction = system_instruction
        if self.error is not None:
            raise self.error
        for token in self.tokens:
            yield token

    async def generate_structured(self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext) -> Any:
        self.usages.append(usage)
        self.generate_structured_calls.append(response_schema)
        self.structured_prompts.append(prompt)
        result = self._structured_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


async def _start_session(client: httpx.AsyncClient, payload: dict[str, object]) -> str:
    resp = await client.post("/preview-sessions", json=payload)
    assert resp.status_code == 201
    session_id = resp.json()["previewSessionId"]
    assert isinstance(session_id, str)
    return session_id


async def test_send_preview_message_requires_login(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()
    resp = await api_client.post(f"/preview-sessions/{uuid.uuid4().hex}/messages", json={"content": "안녕"})
    assert resp.status_code == 401


async def test_send_preview_message_unknown_session_404(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    # `send_message`'s CLAUDE.md gotcha applies here too: every request past login needs
    # `get_llm_client` overridden, even ones that end up failing on an earlier Depends().
    _override_llm_client(_FakeLLMClient(tokens=[]))
    try:
        resp = await db_client.post(f"/preview-sessions/{uuid.uuid4().hex}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 404


async def test_send_preview_message_character_streams_and_appends(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    session_id = await _start_session(db_client, _character_payload())

    fake = _FakeLLMClient(tokens=["안", "녕"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "안녕!"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "token", "done"]
    assert events[-1]["finalMessage"]["content"] == "안녕"
    # Character preview never judges stats/endings.
    assert fake.generate_structured_calls == []

    state = await get_preview_session(session_id)
    assert state is not None
    assert [m.content for m in state.messages] == ["안녕하세요, 아리아예요", "안녕!", "안녕"]
    assert state.turn_count == 1
    # 캐릭터 챗은 template 없이 동작한다 — L0.5가 붙지 않는다.
    assert fake.received_system_instruction == _read_golden_prompt("system_instruction_character.txt")


async def test_send_preview_message_story_selects_template_instruction(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """`_stream_preview_turn` 호출부는 `payload.prompt_template`을
    골라 시스템 지시문(L0.5)에 잇는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    session_id = await _start_session(db_client, _story_payload(promptTemplate="emotional"))

    fake = _FakeLLMClient(tokens=["이야기"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "안녕!"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_system_instruction is not None
    assert (
        "인물의 감정 변화는 장면 안의 단서로 드러난다 — 표정, 손짓, 목소리의 결. "
        "침묵도 반응이며, 그 침묵이 무엇을 뜻하는지 장면이 알려 준다." in fake.received_system_instruction
    )


async def test_send_preview_message_policy_violation_emits_policy_warning(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`chat/router.py`의 `_stream_preview_turn`은 본 채팅·재생성과 글자 그대로 같은
    `except LLMPolicyViolationError` 핸들러를 갖지만 여태 이 경로만 테스트가 없었다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    session_id = await _start_session(db_client, _character_payload())

    fake = _FakeLLMClient(tokens=[], error=LLMPolicyViolationError("blocked"))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(
            f"/preview-sessions/{session_id}/messages", json={"content": "부적절한 메시지"}
        )
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["policyWarning"]

    state = await get_preview_session(session_id)
    assert state is not None
    # 유저 메시지는 남지만 AI 응답은 저장되지 않고, 실패한 턴은 turn_count에 반영되지 않는다.
    assert state.messages[-1].role == ChatMessageRole.USER
    assert state.messages[-1].content == "부적절한 메시지"
    assert state.turn_count == 0


async def test_send_preview_message_llm_error_emits_error_event(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    session_id = await _start_session(db_client, _character_payload())

    fake = _FakeLLMClient(tokens=[], error=LLMClientError("network down"))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["error"]

    state = await get_preview_session(session_id)
    assert state is not None
    assert state.messages[-1].role == ChatMessageRole.USER
    assert state.messages[-1].content == "안녕"
    assert state.turn_count == 0


async def test_send_preview_message_story_stat_change(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    stat_id = str(uuid.uuid4())
    stat = _stat_def_item(id=stat_id)
    session_id = await _start_session(
        db_client, _story_payload(startingSetups=[_starting_setup_item(statDefs=[stat])])
    )

    fake = _FakeLLMClient(
        tokens=["이야기"],
        structured_results=[StatRuleJudgmentResult(fired_rule_ids=["a1"])],
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "달려간다"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "statChange", "done"]
    assert events[1]["statId"] == stat_id
    assert events[1]["newValue"] == 80
    # No endings registered, so only the stat judgment is called.
    assert fake.generate_structured_calls == [StatRuleJudgmentResult]

    state = await get_preview_session(session_id)
    assert state is not None
    assert state.stats == {stat_id: 80.0}


async def test_send_preview_message_ignores_old_direction_and_step_keys_on_stats(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """옛 빌더 번들은 없어진 변화 방향·한 턴 최대 폭 키를 보낼 수 있다. 미리보기 시작은 그 키를 무시하고 받아 주고, 판정은
    그 두 옵션 없이 규칙 폭만큼 움직인다(감소만·최대 3 이었어도 +30)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    stat_id = str(uuid.uuid4())
    stat = _stat_def_item(id=stat_id, changeDirection="decrease", maxChangePerTurn=3)
    session_id = await _start_session(
        db_client, _story_payload(startingSetups=[_starting_setup_item(statDefs=[stat])])
    )

    fake = _FakeLLMClient(tokens=["이야기"], structured_results=[StatRuleJudgmentResult(fired_rule_ids=["a1"])])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "달려간다"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    state = await get_preview_session(session_id)
    assert state is not None
    assert state.stats == {stat_id: 80.0}


@pytest.mark.parametrize(
    "judgment_error",
    [
        pytest.param(LLMClientError("429 RESOURCE_EXHAUSTED"), id="llm-error"),
        pytest.param(LLMPolicyViolationError("Gemini 가 안전 기준으로 판정 응답을 막았다"), id="safety-block"),
    ],
)
async def test_send_preview_message_judgment_llm_failure_still_completes_the_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, judgment_error: LLMClientError
) -> None:
    """실제 채팅과 동일하게, 판정 LLM 실패는 SSE 제너레이터 밖으로 새지 않고 흡수된다 —
    이미 스트리밍된 응답은 세션에 정상 반영되고 그 턴의 판정만 포기한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    stat_id = str(uuid.uuid4())
    stat = _stat_def_item(id=stat_id)
    session_id = await _start_session(
        db_client, _story_payload(startingSetups=[_starting_setup_item(statDefs=[stat])])
    )

    fake = _FakeLLMClient(tokens=["이야기"], structured_results=[judgment_error])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "달려간다"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert [e["type"] for e in _parse_sse_events(resp.text)] == ["token", "done"]

    state = await get_preview_session(session_id)
    assert state is not None
    assert state.messages[-1].content == "이야기"
    assert state.turn_count == 1
    assert state.stats == {stat_id: 50.0}


async def test_send_preview_message_redis_save_failure_still_completes_the_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`update_preview_session`(Redis SET)이
    실패해도 이미 토큰까지 스트리밍된 뒤라 `done` 이벤트까지 정상적으로 나가고 스트림이
    정상 종료된다(§SSE: `require_legal_consent`가 `get_db_session`을 잡고 있어 미리보기도
    요청 스코프 DB 세션을 쥔 채 스트리밍한다). 설계 판단: 이
    실패는 조용히 흡수한다 — `update_preview_session`은 이미 `ChatDoneEvent`가 yield된
    *뒤에* 불리므로, 이 시점에 추가 이벤트를 보내도 클라이언트가 더 이상 듣고 있다는
    보장이 없다. 대신 이번 턴은 Redis에 반영되지 않는다(다음 조회에서 사라진다) — 그
    손실 자체는 남기고, 로그(`logger.warning`)+`capture_dependency_failure`로만 관측한다."""
    captured: list[tuple[BaseException, str]] = []
    monkeypatch.setattr(
        chat_router,
        "capture_dependency_failure",
        lambda exc, *, dependency: captured.append((exc, dependency)),
    )

    async def _raise_redis_error(session_id: str, state: PreviewSessionState) -> None:
        raise RedisError("redis unavailable")

    monkeypatch.setattr(chat_router, "update_preview_session", _raise_redis_error)

    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    session_id = await _start_session(db_client, _character_payload())

    fake = _FakeLLMClient(tokens=["안", "녕"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "안녕!"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "token", "done"]
    assert events[-1]["finalMessage"]["content"] == "안녕"

    assert len(captured) == 1
    assert isinstance(captured[0][0], RedisError)
    assert captured[0][1] == "redis"

    # 실측(설계 판단의 근거): Redis 쓰기가 실패했으므로 이번 턴은 저장된 세션에 반영되지
    # 않는다 — `_start_session`이 만든 최초 상태(오프닝 메시지 하나뿐)만 여전히 조회된다.
    stored_state = await get_preview_session(session_id)
    assert stored_state is not None
    assert [m.content for m in stored_state.messages] == ["안녕하세요, 아리아예요"]
    assert stored_state.turn_count == 0


async def test_send_preview_message_serialization_failure_at_save_still_completes_the_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """적대적 리뷰 발견 — `update_preview_session`
    (`chat/preview_session.py`)은 `state.model_dump_json(by_alias=True)`을 먼저 계산한
    **뒤에** `redis_client.set(...)`을 부른다. 직렬화 실패는 `RedisError`가 아니라 호출부
    (`send_preview_message`)의 `except RedisError`를 그대로 통과해 SSE 제너레이터를 뚫는다
    (§SSE 폭발 반경) — 위 Redis 저장 실패 테스트와는 다른 실패 지점을 잰다.

    `update_preview_session` 자체는 몽키패치하지 않는다 — `PreviewSessionState.model_dump_json`
    만 갈아 끼워 그 함수의 실제 호출 순서(직렬화 → `redis_client.set`)를 그대로 태우고,
    pydantic이 직렬화 실패 시 실제로 던지는 타입(`PydanticSerializationError`, `ValueError`
    서브클래스, pydantic-core 2.13.4로 직접 확인)으로 재현한다."""
    captured: list[tuple[BaseException, str]] = []
    monkeypatch.setattr(
        chat_router,
        "capture_dependency_failure",
        lambda exc, *, dependency: captured.append((exc, dependency)),
    )

    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    session_id = await _start_session(db_client, _character_payload())

    # `_start_session`(→ `create_preview_session`)이 이미 끝난 뒤에 패치한다 — 그쪽 직렬화는
    # 건드리지 않고 `update_preview_session`의 직렬화만 실패시킨다.
    def _raise_serialization_error(self: PreviewSessionState, *args: Any, **kwargs: Any) -> str:
        raise PydanticSerializationError("boom")

    monkeypatch.setattr(PreviewSessionState, "model_dump_json", _raise_serialization_error)

    fake = _FakeLLMClient(tokens=["안", "녕"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "안녕!"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "token", "done"]
    assert events[-1]["finalMessage"]["content"] == "안녕"

    assert len(captured) == 1
    assert isinstance(captured[0][0], PydanticSerializationError)
    assert captured[0][1] == "redis"


async def test_send_preview_message_keyword_note_injected_into_prompt(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    setup = _starting_setup_item()
    session_id = await _start_session(
        db_client,
        _story_payload(
            startingSetups=[setup],
            keywordNotes=[
                {
                    "id": str(uuid.uuid4()),
                    "infoText": "비밀 통로가 존재한다",
                    "triggerKeywords": ["통로"],
                    "startingSetupId": None,
                }
            ],
        ),
    )

    fake = _FakeLLMClient(tokens=["응답"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "통로를 찾는다"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_prompt is not None
    assert "비밀 통로가 존재한다" in fake.received_prompt


def _keyword_note_item(info_text: str, trigger_keywords: list[str], **options: object) -> dict[str, object]:
    return {"id": str(uuid.uuid4()), "infoText": info_text, "triggerKeywords": trigger_keywords, "startingSetupId": None, **options}


async def _preview_prompts(
    client: httpx.AsyncClient, db_session: AsyncSession, payload: dict[str, object], turns: list[tuple[str, str]]
) -> list[str]:
    """`turns` 는 (사용자 메시지, 그 턴의 모델 응답) 쌍. 턴마다 생성 프롬프트를 모은다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(client, user.id)
    session_id = await _start_session(client, payload)
    fake = _FakeLLMClient(tokens=[])
    prompts: list[str] = []
    _override_llm_client(fake)
    try:
        for message, reply in turns:
            fake.tokens = [reply]
            resp = await client.post(f"/preview-sessions/{session_id}/messages", json={"content": message})
            assert resp.status_code == 200, resp.text
            assert fake.received_prompt is not None
            prompts.append(fake.received_prompt)
    finally:
        _clear_llm_override()
    return prompts


async def test_send_preview_message_loads_keyword_note_from_previous_ai_response(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = _story_payload(
        startingSetups=[_starting_setup_item()],
        keywordNotes=[_keyword_note_item("표지-은빛열쇠 노트", ["은빛열쇠"])],
    )

    prompts = await _preview_prompts(
        db_client, db_session, payload, [("주위를 둘러본다", "바닥에 은빛열쇠가 떨어져 있다."), ("그걸 줍는다", "응답")]
    )

    assert ["표지-은빛열쇠 노트" in prompt for prompt in prompts] == [False, True]


async def test_send_preview_message_applies_keyword_note_options_and_builder_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # 노트 id 를 목록 순서의 역순으로 고른다 — 미리보기가 목록 위치를 순서로 넘기지 않으면 id 순으로 정렬돼 뒤집힌다.
    triggered = [
        {**_keyword_note_item(f"표지-열쇠 노트 {index}", ["열쇠"]), "id": str(uuid.UUID(int=100 - index))}
        for index in range(6)
    ]
    payload = _story_payload(
        startingSetups=[_starting_setup_item()],
        keywordNotes=[
            _keyword_note_item("표지-유지 노트", ["마법사"], stickyTurns=1),
            *triggered,
            _keyword_note_item("표지-상시 노트", [], alwaysOn=True, excludeKeywords=["가짜"]),
        ],
    )

    first, second = await _preview_prompts(
        db_client, db_session, payload, [("마법사와 열쇠", "응답"), ("가짜 이야기", "응답")]
    )

    # 키워드로 열린 노트는 유지 노트 + 열쇠 노트 0~3 의 다섯이 위에서부터 들어가고 나머지 둘이 빠진다.
    assert "표지-열쇠 노트 4" not in first and "표지-열쇠 노트 5" not in first
    assert all(f"표지-열쇠 노트 {index}" in first for index in range(4))
    assert "표지-상시 노트" in first and "표지-유지 노트" in first
    assert "표지-상시 노트" not in second
    assert "표지-유지 노트" in second


async def test_send_preview_message_ignores_person_name_inside_opening_media_tag(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = _story_payload(
        startingSetups=[_starting_setup_item(openingMessage="문이 열린다.\n\n{{img::도희/웃음}}")],
        keywordNotes=[_keyword_note_item("표지-도희 노트", ["도희"])],
    )

    [prompt] = await _preview_prompts(db_client, db_session, payload, [("안녕", "응답")])

    assert "표지-도희 노트" not in prompt


async def test_send_preview_message_shortcut_prompt_injected(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    shortcut_id = str(uuid.uuid4())
    session_id = await _start_session(
        db_client,
        _story_payload(
            startingSetups=[_starting_setup_item()],
            shortcuts=[{"id": shortcut_id, "name": "공격", "description": "적을 공격한다", "prompt": "칼을 휘두른다"}],
        ),
    )

    fake = _FakeLLMClient(tokens=["응답"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(
            f"/preview-sessions/{session_id}/messages", json={"content": "칼을 휘두른다", "shortcutId": shortcut_id}
        )
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_prompt is not None
    assert "칼을 휘두른다" in fake.received_prompt


async def test_send_preview_message_invalid_shortcut_id_400(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    session_id = await _start_session(db_client, _story_payload(startingSetups=[_starting_setup_item()]))

    _override_llm_client(_FakeLLMClient(tokens=[]))
    try:
        resp = await db_client.post(
            f"/preview-sessions/{session_id}/messages",
            json={"content": "안녕", "shortcutId": str(uuid.uuid4())},
        )
    finally:
        _clear_llm_override()
    assert resp.status_code == 400


async def test_send_preview_message_reaches_ending(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    ending = _ending_item(turnCountGate=1)
    # 규칙 있는 스탯을 둬 스탯 판정 호출도 일어나게 한다 — 호출부 귀속(아래)을 두 판정 모두에서 본다.
    session_id = await _start_session(
        db_client, _story_payload(startingSetups=[_starting_setup_item(statDefs=[_stat_def_item()], endings=[ending])])
    )

    fake = _FakeLLMClient(
        tokens=["결말"],
        structured_results=[StatRuleJudgmentResult(fired_rule_ids=[]), EndingJudgmentResult(triggered=True)],
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "결말로 향한다"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "endingReached", "done"]
    assert events[1]["endingId"] == ending["id"]
    assert events[1]["epilogue"] == "모두가 행복하게 살았다."

    state = await get_preview_session(session_id)
    assert state is not None
    assert state.ending_reached is True

    # 미리보기는 방이 없다(room_id=None) — chat_ 값이 섞이면 미리보기 원가가 실사용으로 집계된다.
    assert [u.call_site for u in fake.usages] == ["preview_generate", "preview_stat_judgment", "preview_ending_judgment"]
    assert {(u.user_id, u.room_id) for u in fake.usages} == {(user.id, None)}


def _gte_rule(stat_id: object, threshold: float) -> dict[str, object]:
    return {"kind": "rule", "id": str(uuid.uuid4()), "statId": str(stat_id), "operator": "gte", "threshold": threshold, "nextOp": None}


async def _send_preview(
    client: httpx.AsyncClient, session_id: str, fake: "_FakeLLMClient"
) -> list[dict[str, Any]]:
    _override_llm_client(fake)
    try:
        resp = await client.post(f"/preview-sessions/{session_id}/messages", json={"content": "메시지"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 200
    return _parse_sse_events(resp.text)


async def test_send_preview_message_does_not_call_ending_judgment_when_stat_rule_is_false(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """실채팅과 같이 규칙을 먼저 본다 — 초기값 50 에서 `>= 80` 은 거짓이라 엔딩 판정을 부르지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    stat = _stat_def_item(initialValue=50)
    session_id = await _start_session(
        db_client,
        _story_payload(
            startingSetups=[
                _starting_setup_item(statDefs=[stat], endings=[_ending_item(statRules=[_gte_rule(stat["id"], 80)])])
            ]
        ),
    )

    fake = _FakeLLMClient(tokens=["안녕"], structured_results=[StatRuleJudgmentResult(fired_rule_ids=[])])
    events = await _send_preview(db_client, session_id, fake)

    assert [e["type"] for e in events] == ["token", "done"]
    assert [u.call_site for u in fake.usages] == ["preview_generate", "preview_stat_judgment"]


async def test_send_preview_message_judges_endings_in_order_and_stops_at_first_reached(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """규칙 거짓인 첫 엔딩은 판정 없이 넘어가고, 규칙 참·판정 거짓인 둘째 다음 셋째에서 발동하면 넷째는 판정하지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    stat = _stat_def_item(initialValue=50)
    endings = [
        _ending_item(name="1", statRules=[_gte_rule(stat["id"], 80)]),
        _ending_item(name="2", statRules=[_gte_rule(stat["id"], 40)]),
        _ending_item(name="3", statRules=[_gte_rule(stat["id"], 40)]),
        _ending_item(name="4"),
    ]
    session_id = await _start_session(
        db_client, _story_payload(startingSetups=[_starting_setup_item(statDefs=[stat], endings=endings)])
    )

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_results=[
            StatRuleJudgmentResult(fired_rule_ids=[]),
            EndingJudgmentResult(triggered=False),
            EndingJudgmentResult(triggered=True),
        ],
    )
    events = await _send_preview(db_client, session_id, fake)

    assert [e["type"] for e in events] == ["token", "endingReached", "done"]
    assert events[1]["endingId"] == endings[2]["id"]
    assert fake.generate_structured_calls == [StatRuleJudgmentResult, EndingJudgmentResult, EndingJudgmentResult]


async def test_send_preview_message_treats_rule_on_missing_stat_as_false_and_completes_the_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """빌더는 스탯을 지워도 그 스탯을 가리키는 규칙을 남길 수 있고 미리보기 시작은 이를 막지 않는다. 그 항목은
    거짓이고 턴은 세션에 저장되며, 어느 엔딩·스탯인지 경고로 남긴다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    missing_stat_id = uuid.uuid4()
    ending = _ending_item(statRules=[_gte_rule(missing_stat_id, 0)])
    session_id = await _start_session(
        db_client,
        _story_payload(startingSetups=[_starting_setup_item(statDefs=[_stat_def_item()], endings=[ending])]),
    )

    fake = _FakeLLMClient(tokens=["안녕"], structured_results=[StatRuleJudgmentResult(fired_rule_ids=[])])
    with caplog.at_level(logging.WARNING, logger="api.chat.router"):
        events = await _send_preview(db_client, session_id, fake)

    assert [e["type"] for e in events] == ["token", "done"]
    assert fake.generate_structured_calls == [StatRuleJudgmentResult]
    state = await get_preview_session(session_id)
    assert state is not None
    assert (state.turn_count, state.ending_reached) == (1, False)
    [warning] = [r.getMessage() for r in caplog.records if str(missing_stat_id) in r.getMessage()]
    assert str(ending["id"]) in warning


@pytest.mark.parametrize("scenario", ENDING_PRIORITY_SCENARIOS)
async def test_send_preview_message_judges_priority_stat_group_by_highest_value(
    db_client: httpx.AsyncClient, db_session: AsyncSession, scenario: EndingPriorityScenario
) -> None:
    """실채팅(`test_send_message_judges_priority_stat_group_by_highest_value`)과 같은 시나리오 — 미리보기도 같은 순서
    함수를 써서 판정한 엔딩과 발동한 엔딩이 같아야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    rule_deltas, fired_rule_ids = ending_priority_stat_rules(scenario)
    stats = {
        name: _stat_def_item(
            name=name,
            initialValue=value,
            rules=[{"id": str(uuid.uuid4()), "condition": f"{name} 조건", "delta": rule_deltas[name]}],
        )
        for name, value in scenario.stats.items()
    }
    endings = {
        name: _ending_item(
            name=name,
            judgmentPrompt=ending_priority_marker(name),
            priorityStatId=stats[priority]["id"] if priority is not None else None,
            statRules=[_gte_rule(stats[rule[0]]["id"], rule[1])] if rule is not None else [],
        )
        for name, priority, rule in scenario.endings
    }
    session_id = await _start_session(
        db_client,
        _story_payload(
            startingSetups=[_starting_setup_item(statDefs=list(stats.values()), endings=list(endings.values()))]
        ),
    )

    stat_judgment = StatRuleJudgmentResult(fired_rule_ids=fired_rule_ids)
    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_results=[stat_judgment, *(EndingJudgmentResult(triggered=v) for v in scenario.verdicts)],
    )
    events = await _send_preview(db_client, session_id, fake)

    assert judged_ending_names(fake.structured_prompts, scenario) == scenario.judged
    assert len(fake.structured_prompts) == 1 + len(scenario.judged)
    reached = [e["endingId"] for e in events if e["type"] == "endingReached"]
    assert reached == ([endings[scenario.reached]["id"]] if scenario.reached is not None else [])


async def test_send_preview_message_judges_ending_with_valueless_priority_stat_at_its_own_slot(
    db_client: httpx.AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """빌더는 스탯을 지운 초안으로도 미리보기를 시작할 수 있다. 우선 스탯 값이 없는 엔딩은 무리에서 빠져 제자리에서
    판정되고, 어느 엔딩·스탯인지 경고로 남긴다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    missing_stat_id = uuid.uuid4()
    ending = _ending_item(priorityStatId=str(missing_stat_id))
    session_id = await _start_session(
        db_client,
        _story_payload(startingSetups=[_starting_setup_item(statDefs=[_stat_def_item()], endings=[ending])]),
    )

    fake = _FakeLLMClient(
        tokens=["안녕"],
        structured_results=[StatRuleJudgmentResult(fired_rule_ids=[]), EndingJudgmentResult(triggered=True)],
    )
    with caplog.at_level(logging.WARNING, logger="api.chat.router"):
        events = await _send_preview(db_client, session_id, fake)

    assert [e["type"] for e in events] == ["token", "endingReached", "done"]
    assert events[1]["endingId"] == ending["id"]
    [warning] = [r.getMessage() for r in caplog.records if str(missing_stat_id) in r.getMessage()]
    assert str(ending["id"]) in warning


async def test_send_preview_message_skips_judgment_after_ending_reached(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    ending = _ending_item(turnCountGate=1)
    session_id = await _start_session(
        db_client, _story_payload(startingSetups=[_starting_setup_item(endings=[ending])])
    )

    fake = _FakeLLMClient(tokens=["결말"], structured_results=[EndingJudgmentResult(triggered=True)])
    _override_llm_client(fake)
    try:
        first = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "결말로 향한다"})
        assert first.status_code == 200

        second_fake = _FakeLLMClient(tokens=["그 이후"])
        _override_llm_client(second_fake)
        second = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "계속한다"})
    finally:
        _clear_llm_override()

    assert second.status_code == 200
    events = _parse_sse_events(second.text)
    assert [e["type"] for e in events] == ["token", "done"]
    assert second_fake.generate_structured_calls == []


async def test_preview_messages_do_not_touch_chat_rooms(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    session_id = await _start_session(db_client, _character_payload())

    fake = _FakeLLMClient(tokens=["안녕"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "안녕!"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    count = await db_session.scalar(select(func.count()).select_from(ChatRoom))
    assert count == 0


# ---- 대화 프로필 ---------------------


async def test_send_preview_message_injects_the_authors_default_persona(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """미리보기는 작가 본인의 **기본** 프로필을 쓴다. 기본이 아닌 프로필을 하나 더 둬서
    "유저의 아무 프로필"이 아니라 기본을 고른다는 것을 가른다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    not_default = UserPersona(user_id=user.id, name="바다", gender="male", description="기본 아님")
    default = UserPersona(user_id=user.id, name="하늘", gender="female", description="밤하늘을 좋아한다")
    db_session.add_all([not_default, default])
    await db_session.flush()
    user.default_persona_id = default.id
    await db_session.flush()
    await _login_as(db_client, user.id)
    session_id = await _start_session(db_client, _character_payload())

    fake = _FakeLLMClient(tokens=["안녕"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "안녕!"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_prompt is not None
    assert "이름: 하늘\n성별: 여성\n설명: 밤하늘을 좋아한다" in fake.received_prompt
    assert "바다" not in fake.received_prompt


async def test_send_preview_message_story_injects_the_authors_default_persona(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`build_preview_prompt`의 **스토리** 분기도 기본 프로필을 싣는다(위 테스트는 캐릭터
    payload라 캐릭터 분기만 탄다)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    persona = UserPersona(user_id=user.id, name="하늘", gender="male", description="바다를 좋아한다")
    db_session.add(persona)
    await db_session.flush()
    user.default_persona_id = persona.id
    await db_session.flush()
    await _login_as(db_client, user.id)
    session_id = await _start_session(db_client, _story_payload(startingSetups=[_starting_setup_item()]))

    fake = _FakeLLMClient(tokens=["이야기"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "안녕!"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_prompt is not None
    assert "이름: 하늘\n성별: 남성\n설명: 바다를 좋아한다" in fake.received_prompt


async def test_send_preview_message_without_default_persona_has_no_persona_section(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """기본이 없으면 빈 상태다 — 프로필을 갖고 있어도 기본이 아니면 들어가지
    않는다. 섹션 머리글(확정 문안의 첫 줄)이 없는 것으로 섹션째 드롭됐음을 본다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserPersona(user_id=user.id, name="바다", gender=None, description=""))
    await db_session.flush()
    await _login_as(db_client, user.id)
    session_id = await _start_session(db_client, _character_payload())

    fake = _FakeLLMClient(tokens=["안녕"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "안녕!"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_prompt is not None
    assert "[사용자 정보]" not in fake.received_prompt
    assert "바다" not in fake.received_prompt


@pytest.mark.parametrize(
    ("persona_name", "expected_setting", "expected_prologue"),
    [
        pytest.param("지훈", "지훈의 세계\n", "지훈은 문 앞에 선다.", id="authors-default-persona"),
        pytest.param(None, "모험가의 세계\n", "모험가는 문 앞에 선다.", id="draft-default-name"),
    ],
)
async def test_send_preview_message_names_the_user_like_a_real_room(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    persona_name: str | None,
    expected_setting: str,
    expected_prologue: str,
) -> None:
    """미리보기는 실제 방과 같은 규칙으로 이름을 고른다 — 작가의 기본 프로필, 없으면 초안의 작품 기본 이름. 프로필이
    없을 때만 생성 채널에 이름 한 줄이 실린다. 사용자 메시지는 그대로다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    if persona_name is not None:
        persona = UserPersona(user_id=user.id, name=persona_name, gender=None, description="")
        db_session.add(persona)
        await db_session.flush()
        user.default_persona_id = persona.id
        await db_session.flush()
    await _login_as(db_client, user.id)
    session_id = await _start_session(
        db_client,
        _story_payload(
            settingText="{{user}}의 세계",
            defaultUserName="모험가",
            startingSetups=[_starting_setup_item(prologue="{{user}}는 문 앞에 선다.")],
        ),
    )

    fake = _FakeLLMClient(tokens=["이야기"])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "{{user}}라고 쳤다"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    prompt = fake.received_prompt
    assert prompt is not None
    assert prompt.startswith(expected_setting)
    # 프롤로그는 프롤로그 자리와 첫 메시지(대화 기록) 두 곳에 실린다.
    assert prompt.count(expected_prologue) == 2
    assert prompt.count("{{user}}") == 1
    assert ("[사용자 이름]\n대화 속 사용자의 이름: 모험가" in prompt) is (persona_name is None)


def test_send_preview_message_resolves_persona_before_the_clover_charge() -> None:
    """`Depends`는 시그니처
    순서대로 resolve되고 앞의 것이 raise하면 뒤는 불리지 않는다. 프로필 조회가 차감
    게이트보다 뒤에 있으면 조회 실패(DB 장애) 때 차감만 남는다."""
    dependencies = [
        param.default.dependency
        for param in inspect.signature(chat_router.send_preview_message).parameters.values()
        if hasattr(param.default, "dependency")
    ]
    assert dependencies.index(chat_router._preview_persona_dependency) < dependencies.index(
        enforce_chat_rate_limit
    )
