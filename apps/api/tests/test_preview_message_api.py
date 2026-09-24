import inspect
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
    StatChangeJudgment,
    StatJudgmentResult,
)
from api.chat.preview_session import get_preview_session
from api.chat.schemas import PreviewSessionState
from api.core.rate_limit_gate import enforce_chat_rate_limit
from api.db.models.chat import ChatMessageRole, ChatRoom
from api.db.models.persona import UserPersona
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, LLMPolicyViolationError
from factories import (
    _clear_llm_override,
    _login_as,
    _make_user,
    _override_llm_client,
    _parse_sse_events,
    _read_golden_prompt,
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
        self.received_prompt: str | None = None
        self.received_system_instruction: str | None = None
        self.error = error

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.received_prompt = prompt
        self.received_system_instruction = system_instruction
        if self.error is not None:
            raise self.error
        for token in self.tokens:
            yield token

    async def generate_structured(self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext) -> Any:
        self.generate_structured_calls.append(response_schema)
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
    # 캐릭터 챗은 template 없이 동작한다(D-17) — L0.5가 붙지 않는다.
    assert fake.received_system_instruction == _read_golden_prompt("system_instruction_character.txt")


async def test_send_preview_message_story_selects_template_instruction(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """chat-techspec.md §4-2 — `_stream_preview_turn` 호출부는 `payload.prompt_template`을
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
        structured_results=[StatJudgmentResult(stat_changes=[StatChangeJudgment(stat_id=stat_id, new_value=80)])],
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
    assert fake.generate_structured_calls == [StatJudgmentResult]

    state = await get_preview_session(session_id)
    assert state is not None
    assert state.stats == {stat_id: 80.0}


async def test_send_preview_message_judgment_llm_failure_still_completes_the_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession
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

    fake = _FakeLLMClient(tokens=["이야기"], structured_results=[LLMClientError("429 RESOURCE_EXHAUSTED")])
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
    """sse-assert-goal-prompt.md SA-4/CP-4 판정① — `update_preview_session`(Redis SET)이
    실패해도 이미 토큰까지 스트리밍된 뒤라 `done` 이벤트까지 정상적으로 나가고 스트림이
    정상 종료된다(§SSE: `require_legal_consent`가 `get_db_session`을 잡고 있어 미리보기도
    요청 스코프 DB 세션을 쥔 채 스트리밍한다, F-6). 설계 판단(progress.md CP-4 기록): 이
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
    """sse-assert-progress.md SP-129/SP-130(적대적 리뷰 결함②) — `update_preview_session`
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

    fake = _FakeLLMClient(tokens=["응답"], structured_results=[StatJudgmentResult(stat_changes=[])])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "통로를 찾는다"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_prompt is not None
    assert "비밀 통로가 존재한다" in fake.received_prompt


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

    fake = _FakeLLMClient(tokens=["응답"], structured_results=[StatJudgmentResult(stat_changes=[])])
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
    session_id = await _start_session(
        db_client, _story_payload(startingSetups=[_starting_setup_item(endings=[ending])])
    )

    fake = _FakeLLMClient(
        tokens=["결말"],
        structured_results=[StatJudgmentResult(stat_changes=[]), EndingJudgmentResult(triggered=True)],
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


async def test_send_preview_message_skips_judgment_after_ending_reached(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    ending = _ending_item(turnCountGate=1)
    session_id = await _start_session(
        db_client, _story_payload(startingSetups=[_starting_setup_item(endings=[ending])])
    )

    fake = _FakeLLMClient(
        tokens=["결말"],
        structured_results=[StatJudgmentResult(stat_changes=[]), EndingJudgmentResult(triggered=True)],
    )
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


# ---- 대화 프로필 (persona-goal-prompt.md UP-10 · §3-5 · §4 S4 ⑤) ---------------------


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


async def test_send_preview_message_without_default_persona_has_no_persona_section(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """UP-6·UP-10: 기본이 없으면 빈 상태다 — 프로필을 갖고 있어도 기본이 아니면 들어가지
    않는다. 섹션 머리글(§3-4-3 확정 문안의 첫 줄)이 없는 것으로 섹션째 드롭됐음을 본다."""
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


def test_send_preview_message_resolves_persona_before_the_clover_charge() -> None:
    """persona-goal-prompt.md §3-5 (clover-goal-prompt.md CL-1) — `Depends`는 시그니처
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
