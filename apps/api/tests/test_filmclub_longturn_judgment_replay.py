"""판정 리플레이 도구를 LLM 없이 본다 — 대화 전체가 실리는지, 리플레이 call_site 가 원래 판정과 같은 모델을 고르는지,
요청 단위 타임아웃이 리플레이 값으로 나가는지, 호출 상한을 지키는지."""

import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import EndingJudgmentResult, ImageMatchJudgmentResult
from api.core.config import settings
from api.db.models.chat import ChatRoom
from api.db.models.story import Ending, StartingSetup
from api.llm import gemini
from api.llm.client import structured_model
from api.llm.gemini import GeminiLLMClient
from experiments.filmclub_longturn import judgment_replay as replay
from factories import Room, _add_named_media_cell, _open_room, _plant_snapshot

EARLIEST_USER_TEXT = "[U01]"


async def _story_room(db_client: httpx.AsyncClient, db_session: AsyncSession, turns: int = 12) -> Room:
    """12턴 스토리 방 — 칸 하나, 턴 10에 판정 차례인 엔딩 하나, 턴 8까지 덮는 요약."""
    room = await _open_room(db_client, db_session, turns=turns, lane="story")
    row = await db_session.get(ChatRoom, room.room_id)
    assert row is not None
    await _add_named_media_cell(
        db_session, row.content_version_id, room.user_id, "도희", "기획 회의", situation_description="회의"
    )
    setup = await db_session.scalar(
        sa.select(StartingSetup).where(StartingSetup.content_version_id == row.content_version_id)
    )
    assert setup is not None
    db_session.add(
        Ending(
            entity_id=uuid.uuid4(),
            starting_setup_id=setup.id,
            name="엔딩",
            turn_count_gate=10,
            judgment_prompt="상영회를 마쳤는가?",
            epilogue=None,
            hint=None,
            order=1,
        )
    )
    await db_session.commit()
    await _plant_snapshot(db_session, room, turn=8, text="8턴까지의 요약")
    return room


async def test_full_variant_puts_the_whole_history_into_both_judgments(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _story_room(db_client, db_session)
    inputs = await replay.build_inputs(db_session, room.room_id, 10, kinds=["image", "ending"], variant="full")
    assert [(i.kind, i.call_site, i.original_call_site) for i in inputs] == [
        ("image", "replay_media_book_image", "chat_media_book_image"),
        ("ending", "replay_ending_judgment", "chat_ending_judgment"),
    ]
    for item in inputs:
        assert EARLIEST_USER_TEXT in item.prompt
        assert "[U10]" in item.prompt and "[A10]" in item.prompt  # 그 턴의 사용자·응답
        assert "[U11]" not in item.prompt  # 그 턴 뒤는 없다
        assert item.history_messages == 1 + 2 * 9
    assert "8턴까지의 요약" not in inputs[1].prompt  # 전체 히스토리면 요약을 싣지 않는다


async def test_window_variant_drops_summarised_turns_like_the_live_judgment(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _story_room(db_client, db_session)
    before = (settings.memory_window_image_judgment, settings.memory_window_ending_judgment)
    full = await replay.build_inputs(db_session, room.room_id, 12, kinds=["image"], variant="full")
    window = await replay.build_inputs(db_session, room.room_id, 12, kinds=["image"], variant="window")
    assert EARLIEST_USER_TEXT in full[0].prompt
    assert EARLIEST_USER_TEXT not in window[0].prompt
    assert window[0].history_messages < full[0].history_messages
    # 이 프로세스에서 바꾼 판정 윈도 설정은 끝나면 원래대로 돌아온다.
    assert (settings.memory_window_image_judgment, settings.memory_window_ending_judgment) == before


async def test_window_variant_is_refused_for_a_past_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _story_room(db_client, db_session)
    with pytest.raises(ValueError, match="마지막 턴"):
        await replay.build_inputs(db_session, room.room_id, 10, kinds=["image"], variant="window")


def _fake_gemini(monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]) -> GeminiLLMClient:
    async def generate_content(**kwargs: Any) -> SimpleNamespace:
        sent.append(kwargs)
        schema = kwargs["config"].response_schema
        parsed = (
            EndingJudgmentResult(triggered=False)
            if schema is EndingJudgmentResult
            else ImageMatchJudgmentResult(matched_image_entity_id=None)
        )
        return SimpleNamespace(parsed=parsed, usage_metadata=SimpleNamespace(prompt_token_count=123))

    client = GeminiLLMClient(api_key="test-key")
    monkeypatch.setattr(
        client,
        "_client",
        SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))),
    )
    return client


async def test_replay_calls_use_the_original_judgment_model_replay_label_and_long_timeout(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "gemini_ending_judgment_model_name", "ending-model")
    monkeypatch.setattr(settings, "gemini_image_judgment_model_name", None)
    recorded: list[tuple[str, str]] = []

    async def record_usage(call_site: str, model: str, usage: object) -> None:
        recorded.append((call_site, model))

    monkeypatch.setattr(gemini, "record_usage", record_usage)
    room = await _story_room(db_client, db_session)
    row = await db_session.get(ChatRoom, room.room_id)
    assert row is not None
    inputs = await replay.build_inputs(db_session, room.room_id, 10, kinds=["image", "ending"], variant="full")
    models = replay.check_same_models(inputs, settings.gemini_model_name)
    assert models == {
        "replay_media_book_image": structured_model("chat_media_book_image", settings.gemini_model_name),
        "replay_ending_judgment": "ending-model",
    }

    sent: list[dict[str, Any]] = []
    client = _fake_gemini(monkeypatch, sent)
    capture: dict[str, Any] = {}
    replay.install_replay_transport(client, capture)
    records: list[dict[str, Any]] = []
    await replay.run_replay(
        client, capture, inputs, reps=1, budget=replay.CallBudget(10), room=row, sink=records.append
    )

    assert [k["model"] for k in sent] == [settings.gemini_model_name, "ending-model"]
    assert [k["config"].http_options.timeout for k in sent] == [replay.REPLAY_TIMEOUT_MS] * 2
    assert [k["contents"] for k in sent] == [i.prompt for i in inputs]
    assert recorded == [
        ("replay_media_book_image", settings.gemini_model_name),
        ("replay_ending_judgment", "ending-model"),
    ]
    assert [(r["callSite"], r["sentModel"], r["sentTimeoutMs"], r["error"]) for r in records] == [
        ("replay_media_book_image", settings.gemini_model_name, replay.REPLAY_TIMEOUT_MS, None),
        ("replay_ending_judgment", "ending-model", replay.REPLAY_TIMEOUT_MS, None),
    ]


def test_model_check_stops_when_a_replay_site_would_pick_another_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gemini_ending_judgment_model_name", "ending-model")
    item = replay.ReplayInput(
        kind="ending",
        variant="full",
        turn=10,
        prompt="p",
        schema=EndingJudgmentResult,
        call_site="chat_generate",  # 판정 집합 밖 — 기본 모델로 간다
        original_call_site="chat_ending_judgment",
        history_messages=1,
    )
    with pytest.raises(ValueError, match="ending-model"):
        replay.check_same_models([item], "default-model")


async def test_call_budget_is_a_hard_cap(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def record_usage(*_: object) -> None:
        return None

    monkeypatch.setattr(gemini, "record_usage", record_usage)
    room = await _story_room(db_client, db_session)
    row = await db_session.get(ChatRoom, room.room_id)
    assert row is not None
    inputs = await replay.build_inputs(db_session, room.room_id, 10, kinds=["image", "ending"], variant="full")
    sent: list[dict[str, Any]] = []
    client = _fake_gemini(monkeypatch, sent)
    capture: dict[str, Any] = {}
    replay.install_replay_transport(client, capture)
    records: list[dict[str, Any]] = []
    await replay.run_replay(client, capture, inputs, reps=2, budget=replay.CallBudget(3), room=row, sink=records.append)
    assert len(sent) == 3
    assert records[-1]["kind"] == "budgetExhausted"


def test_estimate_grows_with_the_turn_number() -> None:
    def item(turn: int) -> replay.ReplayInput:
        return replay.ReplayInput(
            kind="ending",
            variant="full",
            turn=turn,
            prompt="p",
            schema=EndingJudgmentResult,
            call_site="replay_ending_judgment",
            original_call_site="chat_ending_judgment",
            history_messages=1,
        )

    models = {"replay_ending_judgment": "gemini-3.1-flash-lite"}
    small = replay.estimate([item(100)], 1, models)
    large = replay.estimate([item(500)], 2, models)
    assert small["calls"] == 1 and large["calls"] == 2
    assert large["tokensPerCall"] == [replay.TOKENS_PER_TURN * 500]
    assert large["estimatedUsd"] > small["estimatedUsd"] > 0
