"""측정 브랜치 전용 계측 trace 를 본다 — 스탯 판정의 요청값 대 적용값, 호출별 경과 ms, 기본 꺼짐, 기록 실패 삼킴.
판정 리플레이의 요청 타임아웃이 실제 SDK 요청에 어떤 값으로 실리는지도 여기서 본다(가짜 HTTP 전송, LLM 0)."""

import json
import os
import uuid
from pathlib import Path
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import EndingJudgmentResult, StatChangeJudgment, StatJudgmentResult
from api.core import filmclub_trace
from api.core.config import Settings, settings
from api.llm.client import LLMCallContext, LLMClientError
from api.llm.gemini import GeminiLLMClient
from experiments.filmclub_longturn import judgment_replay as replay
from api.db.models.story import StatDef
from api.llm.client import LLMClient
from factories import _clear_llm_override, _login_as, _override_llm_client, _parse_sse_events, _story_with_setup


def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_trace_path_defaults_to_off() -> None:
    assert Settings.model_fields["filmclub_trace_path"].default is None


def test_write_does_nothing_when_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "filmclub_trace_path", None)
    monkeypatch.chdir(tmp_path)
    filmclub_trace.write_trace("llm_call", callSite="chat_generate")
    assert list(tmp_path.iterdir()) == []


class _StatJudgingLLMClient(LLMClient):
    """생성은 고정 토큰, 판정은 고정 스탯 결과. 판정 호출 순간 trace 문맥의 턴 번호를 잡아 둔다 — 클라이언트 층
    기록이 같은 턴으로 묶이는지 본다."""

    def __init__(self, result: StatJudgmentResult) -> None:
        self.result = result
        self.seen_turn: int | None = None

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        yield "안녕"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.seen_turn = filmclub_trace.current_turn()
        return self.result


def _stat_def(setup_id: uuid.UUID, name: str, order: int, **overrides: object) -> StatDef:
    fields: dict[str, object] = {
        "entity_id": uuid.uuid4(),
        "starting_setup_id": setup_id,
        "name": name,
        "icon": "heart",
        "color": "#ff0000",
        "min_value": 0,
        "max_value": 100,
        "unit": None,
        "description": name,
        "order": order,
        **overrides,
    }
    return StatDef(**fields)


async def _story_room_with_two_stats(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> tuple[uuid.UUID, StatDef, StatDef]:
    """호감(폭 7, 양방향, 시작 50)과 남은 날(감소만, 시작 30) 두 스탯의 스토리 방."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message=None)
    affection = _stat_def(setup.id, "호감", 1, initial_value=50, max_change_per_turn=7)
    days = _stat_def(setup.id, "남은 날", 2, initial_value=30, change_direction="decrease")
    db_session.add_all([affection, days])
    await db_session.commit()
    await _login_as(db_client, user_id)
    created = await db_client.post(
        "/chat-rooms",
        json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)},
    )
    return uuid.UUID(created.json()["id"]), affection, days


def _judging(*pairs: tuple[StatDef, float]) -> _StatJudgingLLMClient:
    return _StatJudgingLLMClient(
        StatJudgmentResult(
            stat_changes=[StatChangeJudgment(stat_id=str(d.entity_id), new_value=v) for d, v in pairs]
        )
    )


async def test_story_turn_traces_requested_and_applied_stat_values(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    monkeypatch.setattr(settings, "filmclub_trace_path", str(trace_path))
    room_id, affection, days = await _story_room_with_two_stats(db_client, db_session)

    # 호감은 폭 7 을 넘는 요청이라 57 로 잘리고, "감소만" 스탯의 증가 요청은 시작 값에 머문다.
    fake = _judging((affection, 70), (days, 35))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "칭찬했다"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 200

    outcomes = [r for r in _records(trace_path) if r["kind"] == "stat_outcome"]
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome["roomId"] == str(room_id)
    assert outcome["turn"] == 1
    by_name = {s["name"]: s for s in outcome["stats"]}
    assert by_name["호감"] == {
        "statId": str(affection.entity_id),
        "name": "호감",
        "start": 50.0,
        "requested": 70.0,
        "applied": 57.0,
        "maxChangePerTurn": 7,
        "changeDirection": "both",
        "clamped": True,
    }
    assert by_name["남은 날"]["requested"] == 35.0
    assert by_name["남은 날"]["applied"] == 30.0
    assert by_name["남은 날"]["clamped"] is True
    # 판정 호출이 같은 턴 문맥 안에서 나간다 — 클라이언트 층 기록이 이 턴 번호를 단다.
    assert fake.seen_turn == 1


async def test_unrequested_stat_is_traced_as_not_requested(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    monkeypatch.setattr(settings, "filmclub_trace_path", str(trace_path))
    room_id, affection, _ = await _story_room_with_two_stats(db_client, db_session)

    fake = _judging((affection, 53))
    _override_llm_client(fake)
    try:
        await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "인사"})
    finally:
        _clear_llm_override()

    (outcome,) = [r for r in _records(trace_path) if r["kind"] == "stat_outcome"]
    by_name = {s["name"]: s for s in outcome["stats"]}
    assert by_name["호감"]["clamped"] is False
    assert by_name["남은 날"]["requested"] is None
    assert by_name["남은 날"]["clamped"] is False


async def test_trace_write_failure_does_not_break_the_turn(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # 디렉터리는 append 로 열 수 없다 — 기록이 실패해도 턴은 끝까지 간다.
    monkeypatch.setattr(settings, "filmclub_trace_path", str(tmp_path))
    room_id, affection, _ = await _story_room_with_two_stats(db_client, db_session)

    fake = _judging((affection, 70))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "칭찬했다"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "statChange", "done"]
    assert events[1]["newValue"] == 57


# ── 클라이언트 층: 호출별 경과 ms ─────────────────────────────────────────────


def _fake_sdk_client(monkeypatch: pytest.MonkeyPatch, **models: Any) -> GeminiLLMClient:
    client = GeminiLLMClient(api_key="test-key", model_name="gen-model")
    monkeypatch.setattr(client, "_client", SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(**models))))
    return client


async def test_structured_call_traces_elapsed_ms_with_call_site_and_chosen_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    monkeypatch.setattr(settings, "filmclub_trace_path", str(trace_path))
    monkeypatch.setattr(settings, "gemini_ending_judgment_model_name", "judge-model")
    room_id = uuid.uuid4()

    async def generate_content(**_: Any) -> Any:
        return SimpleNamespace(parsed=EndingJudgmentResult(triggered=False), usage_metadata=None)

    client = _fake_sdk_client(monkeypatch, generate_content=generate_content)
    usage = LLMCallContext(call_site="chat_ending_judgment", user_id=None, room_id=room_id)
    await client.generate_structured("p", EndingJudgmentResult, usage=usage)

    (record,) = _records(trace_path)
    assert record["kind"] == "llm_call"
    assert record["callSite"] == "chat_ending_judgment"
    assert record["model"] == "judge-model"
    assert record["roomId"] == str(room_id)
    assert record["ok"] is True
    assert isinstance(record["elapsedMs"], int) and record["elapsedMs"] >= 0


async def test_failed_structured_call_is_traced_with_its_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    monkeypatch.setattr(settings, "filmclub_trace_path", str(trace_path))

    async def generate_content(**_: Any) -> Any:
        raise genai_errors.APIError(code=503, response_json={"error": {"message": "unavailable"}})

    client = _fake_sdk_client(monkeypatch, generate_content=generate_content)
    usage = LLMCallContext(call_site="chat_stat_judgment", user_id=None, room_id=None)
    with pytest.raises(LLMClientError):
        await client.generate_structured("p", EndingJudgmentResult, usage=usage)

    (record,) = _records(trace_path)
    assert record["callSite"] == "chat_stat_judgment"
    assert record["ok"] is False
    assert record["errorType"] == "APIError"
    assert isinstance(record["elapsedMs"], int)


async def test_streamed_generation_is_traced_once_after_the_stream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    monkeypatch.setattr(settings, "filmclub_trace_path", str(trace_path))

    async def chunks() -> Any:
        for text in ("a", "b"):
            yield SimpleNamespace(text=text)

    async def generate_content_stream(**_: Any) -> Any:
        return chunks()

    client = _fake_sdk_client(monkeypatch, generate_content_stream=generate_content_stream)
    usage = LLMCallContext(call_site="chat_generate", user_id=None, room_id=None)
    assert [t async for t in client.generate("p", usage=usage)] == ["a", "b"]

    (record,) = _records(trace_path)
    assert record["callSite"] == "chat_generate"
    assert record["model"] == "gen-model"
    assert record["ok"] is True


async def test_client_layer_writes_nothing_when_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "filmclub_trace_path", None)
    monkeypatch.chdir(tmp_path)

    async def generate_content(**_: Any) -> Any:
        return SimpleNamespace(parsed=EndingJudgmentResult(triggered=False), usage_metadata=None)

    client = _fake_sdk_client(monkeypatch, generate_content=generate_content)
    usage = LLMCallContext(call_site="chat_ending_judgment", user_id=None, room_id=None)
    await client.generate_structured("p", EndingJudgmentResult, usage=usage)
    assert os.listdir(tmp_path) == []


# ── 판정 리플레이의 실제 요청 타임아웃 ──────────────────────────────────────────


def _http_client_capturing(sent: list[httpx.Request]) -> GeminiLLMClient:
    """진짜 SDK 를 쓰되 HTTP 전송만 가짜로 바꾼 클라이언트. SDK 가 요청에 실은 읽기 타임아웃과 서버 기한 헤더를 본다."""

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        body = {
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": '{"triggered": false}'}]}, "finishReason": "STOP"}
            ],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3, "totalTokenCount": 13},
        }
        return httpx.Response(200, json=body)

    client = GeminiLLMClient(api_key="test-key")
    client._client = genai.Client(
        api_key="test-key",
        http_options=genai_types.HttpOptions(
            timeout=settings.gemini_client_timeout_ms,
            httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
    )
    return client


_REPLAY_USAGE = LLMCallContext(call_site="replay_ending_judgment", user_id=None, room_id=None)


async def test_replay_call_site_alone_gets_the_judgment_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """리플레이 call_site 는 판정 집합에 들어 있어, 덮지 않으면 판정 상한으로 나간다."""
    monkeypatch.setattr(settings, "gemini_judgment_timeout_ms", 20_000)
    sent: list[httpx.Request] = []
    client = _http_client_capturing(sent)

    await client.generate_structured("p", EndingJudgmentResult, usage=_REPLAY_USAGE)

    assert sent[0].extensions["timeout"]["read"] == 20.0
    assert sent[0].headers["X-Server-Timeout"] == "20"


async def test_replay_transport_puts_the_long_timeout_on_the_real_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """리플레이 도구가 덮은 값이 SDK 를 지나 실제 HTTP 요청의 읽기 타임아웃·서버 기한 헤더까지 간다."""
    monkeypatch.setattr(settings, "gemini_judgment_timeout_ms", 20_000)
    sent: list[httpx.Request] = []
    client = _http_client_capturing(sent)
    replay.install_replay_transport(client, {})

    for _ in range(2):
        await client.generate_structured("p", EndingJudgmentResult, usage=_REPLAY_USAGE)

    assert [r.extensions["timeout"]["read"] for r in sent] == [replay.REPLAY_TIMEOUT_MS / 1000] * 2
    assert [r.headers["X-Server-Timeout"] for r in sent] == [str(replay.REPLAY_TIMEOUT_MS // 1000)] * 2
