import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import EndingJudgmentResult, StatChangeJudgment, StatJudgmentResult
from api.chat.preview_session import get_preview_session
from api.db.models.chat import ChatRoom
from api.llm.client import LLMClient
from api.llm.dependencies import get_llm_client
from api.main import app


async def _login_as(client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    resp = await client.post("/dev/session-echo", json={"data": {"user_id": str(user_id)}})
    assert resp.status_code == 201


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

    def __init__(self, tokens: list[str], structured_results: list[Any] | None = None) -> None:
        self.tokens = tokens
        self._structured_results = list(structured_results or [])
        self.generate_structured_calls: list[Any] = []
        self.received_prompt: str | None = None

    async def generate(self, prompt: str) -> AsyncIterator[str]:
        self.received_prompt = prompt
        for token in self.tokens:
            yield token

    async def generate_structured(self, prompt: str, response_schema: Any, images: Any = None) -> Any:
        self.generate_structured_calls.append(response_schema)
        return self._structured_results.pop(0)


def _override_llm_client(fake: _FakeLLMClient) -> None:
    app.dependency_overrides[get_llm_client] = lambda: fake


def _clear_llm_override() -> None:
    app.dependency_overrides.pop(get_llm_client, None)


def _parse_sse_events(body: str) -> list[dict[str, Any]]:
    events = []
    for chunk in body.split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
    return events


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


async def test_send_preview_message_unknown_session_404(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()
    await _login_as(api_client, uuid.uuid4())

    # `send_message`'s CLAUDE.md gotcha applies here too: every request past login needs
    # `get_llm_client` overridden, even ones that end up failing on an earlier Depends().
    _override_llm_client(_FakeLLMClient(tokens=[]))
    try:
        resp = await api_client.post(f"/preview-sessions/{uuid.uuid4().hex}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 404


async def test_send_preview_message_character_streams_and_appends(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()
    await _login_as(api_client, uuid.uuid4())
    session_id = await _start_session(api_client, _character_payload())

    fake = _FakeLLMClient(tokens=["안", "녕"])
    _override_llm_client(fake)
    try:
        resp = await api_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "안녕!"})
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


async def test_send_preview_message_story_stat_change(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()
    await _login_as(api_client, uuid.uuid4())
    stat_id = str(uuid.uuid4())
    stat = _stat_def_item(id=stat_id)
    session_id = await _start_session(
        api_client, _story_payload(startingSetups=[_starting_setup_item(statDefs=[stat])])
    )

    fake = _FakeLLMClient(
        tokens=["이야기"],
        structured_results=[StatJudgmentResult(stat_changes=[StatChangeJudgment(stat_id=stat_id, new_value=80)])],
    )
    _override_llm_client(fake)
    try:
        resp = await api_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "달려간다"})
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


async def test_send_preview_message_keyword_note_injected_into_prompt(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()
    await _login_as(api_client, uuid.uuid4())
    setup = _starting_setup_item()
    session_id = await _start_session(
        api_client,
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
        resp = await api_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "통로를 찾는다"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_prompt is not None
    assert "비밀 통로가 존재한다" in fake.received_prompt


async def test_send_preview_message_shortcut_prompt_injected(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()
    await _login_as(api_client, uuid.uuid4())
    shortcut_id = str(uuid.uuid4())
    session_id = await _start_session(
        api_client,
        _story_payload(
            startingSetups=[_starting_setup_item()],
            shortcuts=[{"id": shortcut_id, "name": "공격", "description": "적을 공격한다", "prompt": "칼을 휘두른다"}],
        ),
    )

    fake = _FakeLLMClient(tokens=["응답"], structured_results=[StatJudgmentResult(stat_changes=[])])
    _override_llm_client(fake)
    try:
        resp = await api_client.post(
            f"/preview-sessions/{session_id}/messages", json={"content": "칼을 휘두른다", "shortcutId": shortcut_id}
        )
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_prompt is not None
    assert "칼을 휘두른다" in fake.received_prompt


async def test_send_preview_message_invalid_shortcut_id_400(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()
    await _login_as(api_client, uuid.uuid4())
    session_id = await _start_session(api_client, _story_payload(startingSetups=[_starting_setup_item()]))

    _override_llm_client(_FakeLLMClient(tokens=[]))
    try:
        resp = await api_client.post(
            f"/preview-sessions/{session_id}/messages",
            json={"content": "안녕", "shortcutId": str(uuid.uuid4())},
        )
    finally:
        _clear_llm_override()
    assert resp.status_code == 400


async def test_send_preview_message_reaches_ending(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()
    await _login_as(api_client, uuid.uuid4())
    ending = _ending_item(turnCountGate=1)
    session_id = await _start_session(
        api_client, _story_payload(startingSetups=[_starting_setup_item(endings=[ending])])
    )

    fake = _FakeLLMClient(
        tokens=["결말"],
        structured_results=[StatJudgmentResult(stat_changes=[]), EndingJudgmentResult(triggered=True)],
    )
    _override_llm_client(fake)
    try:
        resp = await api_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "결말로 향한다"})
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


async def test_send_preview_message_skips_judgment_after_ending_reached(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()
    await _login_as(api_client, uuid.uuid4())
    ending = _ending_item(turnCountGate=1)
    session_id = await _start_session(
        api_client, _story_payload(startingSetups=[_starting_setup_item(endings=[ending])])
    )

    fake = _FakeLLMClient(
        tokens=["결말"],
        structured_results=[StatJudgmentResult(stat_changes=[]), EndingJudgmentResult(triggered=True)],
    )
    _override_llm_client(fake)
    try:
        first = await api_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "결말로 향한다"})
        assert first.status_code == 200

        second_fake = _FakeLLMClient(tokens=["그 이후"])
        _override_llm_client(second_fake)
        second = await api_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "계속한다"})
    finally:
        _clear_llm_override()

    assert second.status_code == 200
    events = _parse_sse_events(second.text)
    assert [e["type"] for e in events] == ["token", "done"]
    assert second_fake.generate_structured_calls == []


async def test_preview_messages_do_not_touch_chat_rooms(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as(db_client, uuid.uuid4())
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
