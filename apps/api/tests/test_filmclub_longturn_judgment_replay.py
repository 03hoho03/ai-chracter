"""판정 리플레이 도구를 LLM 없이 본다 — 대화 전체가 실리는지, 리플레이 call_site 가 원래 판정과 같은 모델을 고르는지,
요청 단위 타임아웃이 리플레이 값으로 나가는지, 호출 상한을 지키는지."""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    PromptNames,
    StatChangeJudgment,
    StatJudgmentResult,
)
from api.core.config import settings
from api.db.models.chat import ChatRoom, ChatRoomMemorySnapshot
from api.db.models.story import Ending, StartingSetup, StatDef
from api.llm import gemini
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, structured_model
from api.llm.gemini import GeminiLLMClient
from experiments.filmclub_longturn import judgment_replay as replay
from experiments.filmclub_longturn.replay_budget import CallBudget
from factories import (
    Room,
    _add_named_media_cell,
    _clear_llm_override,
    _login_as,
    _make_default_persona,
    _open_room,
    _override_llm_client,
    _plant_snapshot,
    _story_with_setup,
)

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


async def _plant_snapshot_made_at(
    db_session: AsyncSession, room: Room, *, cursor_turn: int, made_after_turn: int, text: str
) -> None:
    """`cursor_turn` 응답까지 덮는 요약을, `made_after_turn` 응답 직후(다음 사용자 메시지 전)에 만든 것으로 심는다."""
    assistant = room.turns[cursor_turn][1]
    db_session.add(
        ChatRoomMemorySnapshot(
            chat_room_id=room.room_id,
            cursor_created_at=assistant.created_at,
            cursor_message_id=assistant.id,
            summary_text=text,
            source="auto",
            created_at=room.turns[made_after_turn][1].created_at + timedelta(milliseconds=500),
        )
    )
    await db_session.commit()


async def test_window_asof_uses_the_summary_that_existed_when_that_turn_was_judged(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # _story_room 의 턴 8 요약은 모든 메시지 뒤에 만들어졌다 — 어느 턴의 판정 때도 아직 없었다.
    room = await _story_room(db_client, db_session)
    await _plant_snapshot_made_at(db_session, room, cursor_turn=4, made_after_turn=6, text="4턴까지")
    full = await replay.build_inputs(db_session, room.room_id, 10, kinds=["image"], variant="full")
    asof = await replay.build_inputs(db_session, room.room_id, 10, kinds=["image"], variant="window-asof")
    assert EARLIEST_USER_TEXT in full[0].prompt
    assert "[U04]" not in asof[0].prompt and "[A04]" not in asof[0].prompt  # 커서 이하는 빠진다
    assert "[U05]" in asof[0].prompt and "[U10]" in asof[0].prompt and "[A10]" in asof[0].prompt
    assert "4턴까지" not in asof[0].prompt  # 칸 판정은 요약을 싣지 않는다
    assert asof[0].history_messages == 1 + 2 * 5  # 오프닝 + 턴 5~9
    assert asof[0].variant == "window-asof"


async def test_window_asof_equals_full_before_any_summary_existed(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _story_room(db_client, db_session)
    await _plant_snapshot_made_at(db_session, room, cursor_turn=4, made_after_turn=6, text="4턴까지")
    # 턴 6: 턴 4 요약은 턴 6 응답 뒤에 생겼으니 그 턴 판정 때는 없었다 — 전체와 같다.
    full = await replay.build_inputs(db_session, room.room_id, 6, kinds=["image"], variant="full")
    asof = await replay.build_inputs(db_session, room.room_id, 6, kinds=["image"], variant="window-asof")
    assert asof[0].prompt == full[0].prompt
    # 마지막 턴: `window` 는 지금 요약(턴 8)을 쓰지만, 그 요약은 턴 12 판정 뒤에 생겼다 — as-of 는 턴 4 요약을 쓴다.
    asof_last = await replay.build_inputs(db_session, room.room_id, 12, kinds=["image"], variant="window-asof")
    assert "[U04]" not in asof_last[0].prompt and "[U05]" in asof_last[0].prompt


async def test_window_asof_is_only_for_the_cell_judgment(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _story_room(db_client, db_session)
    with pytest.raises(ValueError, match="칸 판정"):
        await replay.build_inputs(db_session, room.room_id, 10, kinds=["ending"], variant="window-asof")


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
    await replay.run_replay(client, capture, inputs, reps=1, budget=CallBudget(10), room=row, sink=records.append)

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
    await replay.run_replay(client, capture, inputs, reps=2, budget=CallBudget(3), room=row, sink=records.append)
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


# ── 스탯 판정 ────────────────────────────────────────────────────────────────


class _CapturingStatLLM(LLMClient):
    """생성은 고정 토큰, 스탯 판정은 턴마다 정한 값으로 답하며 서버가 실제로 보낸 스탯 판정 프롬프트를 모은다."""

    def __init__(self, stat_id: str, values: list[float]) -> None:
        self.stat_id = stat_id
        self.values = values
        self.stat_prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        yield f"{{{{user}}}} 쪽을 본다 {len(self.stat_prompts)}"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        if response_schema is not StatJudgmentResult:
            raise LLMClientError("이 시험에서는 스탯 판정만 답한다")
        self.stat_prompts.append(prompt)
        value = self.values[len(self.stat_prompts) - 1]
        return StatJudgmentResult(stat_changes=[StatChangeJudgment(stat_id=self.stat_id, new_value=value)])


async def _played_stat_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[uuid.UUID, StatDef, StatDef, _CapturingStatLLM, Path]:
    """프로필 이름이 있는 사용자가 스탯 둘(설명에 {{user}})인 스토리 방에서 두 턴을 실제 API 로 진행한다. trace 를 켜
    턴마다 판정 시작 값이 남는다."""
    trace_path = tmp_path / "trace.jsonl"
    monkeypatch.setattr(settings, "filmclub_trace_path", str(trace_path))
    user_id, content, setup = await _story_with_setup(db_session, opening_message="어서 와요")
    await _make_default_persona(db_session, user_id, "하늘")
    liking = StatDef(
        entity_id=uuid.uuid4(), starting_setup_id=setup.id, name="세빈 호감도", icon="heart", color="#ff0000",
        min_value=0, max_value=100, initial_value=50, unit=None, order=1,
        description="{{user}}가 세빈의 일에 응하면 2~4 오른다.",
    )  # fmt: skip
    days = StatDef(
        entity_id=uuid.uuid4(), starting_setup_id=setup.id, name="상영회까지", icon="clock", color="#00ff00",
        min_value=0, max_value=42, initial_value=42, unit="일", order=2, max_change_per_turn=7,
        change_direction="decrease", description="날이 넘어가면 줄어든다.",
    )  # fmt: skip
    db_session.add_all([liking, days])
    await db_session.commit()
    await _login_as(db_client, user_id)
    created = await db_client.post(
        "/chat-rooms",
        json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)},
    )
    room_id = uuid.UUID(created.json()["id"])
    fake = _CapturingStatLLM(str(liking.entity_id), [53.0, 28.0])
    _override_llm_client(fake)
    try:
        for text in ("{{user}}: 이 정도 각도예요?", "벤치에 앉는다"):
            resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": text})
            assert resp.status_code == 200
    finally:
        _clear_llm_override()
    return room_id, liking, days, fake, trace_path


async def test_stat_replay_rebuilds_exactly_the_prompt_the_server_sent(
    db_client: httpx.AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    room_id, liking, days, fake, trace_path = await _played_stat_room(db_client, db_session, tmp_path, monkeypatch)
    start = replay.stat_start_from_trace(trace_path, room_id, 2)
    assert start == {str(liking.entity_id): 53.0, str(days.entity_id): 42.0}

    (item,) = await replay.build_inputs(db_session, room_id, 2, kinds=["stat"], variant="full", stat_start=start)
    assert (item.kind, item.call_site, item.original_call_site) == (
        "stat",
        "replay_stat_judgment",
        "chat_stat_judgment",
    )
    assert item.prompt == fake.stat_prompts[1]  # 서버가 턴 2 에 실제로 보낸 프롬프트와 글자 하나까지 같다
    assert item.prompt != fake.stat_prompts[0]


async def test_stat_replay_needs_start_values_for_every_stat(
    db_client: httpx.AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # DB 에는 지금 값만 있어 과거 턴의 시작 값을 알 수 없다 — 추정하지 않고 멈춘다.
    room_id, liking, _days, _fake, _trace = await _played_stat_room(db_client, db_session, tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="시작 값"):
        await replay.build_inputs(db_session, room_id, 2, kinds=["stat"], variant="full")
    with pytest.raises(ValueError, match="시작 값"):
        await replay.build_inputs(
            db_session, room_id, 2, kinds=["stat"], variant="full", stat_start={str(liking.entity_id): 53.0}
        )


def test_stat_start_from_trace_refuses_a_missing_or_ambiguous_turn(tmp_path: Path) -> None:
    room = uuid.uuid4()
    path = tmp_path / "trace.jsonl"
    record = {"kind": "stat_outcome", "turn": 13, "roomId": str(room), "stats": [{"statId": "s", "start": 52.5}]}
    other_room = record | {"roomId": str(uuid.uuid4()), "stats": [{"statId": "s", "start": 1.0}]}
    path.write_text("\n".join(json.dumps(r) for r in (record, other_room)) + "\n", encoding="utf-8")
    assert replay.stat_start_from_trace(path, room, 13) == {"s": 52.5}
    with pytest.raises(ValueError, match="없다"):
        replay.stat_start_from_trace(path, room, 12)
    path.write_text("\n".join(json.dumps(r) for r in (record, record)) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="2개"):
        replay.stat_start_from_trace(path, room, 13)


async def test_stat_replay_call_uses_the_stat_model_replay_label_long_timeout_and_applies_server_rules(
    db_client: httpx.AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    room_id, liking, days, _fake, trace_path = await _played_stat_room(db_client, db_session, tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "gemini_stat_judgment_model_name", "stat-model")
    recorded: list[tuple[str, str]] = []

    async def record_usage(call_site: str, model: str, usage: object) -> None:
        recorded.append((call_site, model))

    monkeypatch.setattr(gemini, "record_usage", record_usage)
    start = replay.stat_start_from_trace(trace_path, room_id, 2)
    inputs = await replay.build_inputs(db_session, room_id, 2, kinds=["stat"], variant="full", stat_start=start)
    assert replay.check_same_models(inputs, settings.gemini_model_name) == {"replay_stat_judgment": "stat-model"}

    # 원 출력: 호감 28(−25, 폭 제한 없음이라 그대로), 상영회까지 증가 요청(감소만이라 버려짐), 모르는 id(무시).
    raw = StatJudgmentResult(
        stat_changes=[
            StatChangeJudgment(stat_id=str(liking.entity_id), new_value=28),
            StatChangeJudgment(stat_id=str(days.entity_id), new_value=45),
            StatChangeJudgment(stat_id="모르는-id", new_value=1),
        ]
    )
    sent: list[dict[str, Any]] = []

    async def generate_content(**kwargs: Any) -> SimpleNamespace:
        sent.append(kwargs)
        return SimpleNamespace(parsed=raw, usage_metadata=SimpleNamespace(prompt_token_count=1743))

    client = GeminiLLMClient(api_key="test-key")
    monkeypatch.setattr(
        client,
        "_client",
        SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))),
    )
    capture: dict[str, Any] = {}
    replay.install_replay_transport(client, capture)
    records: list[dict[str, Any]] = []
    row = await db_session.get(ChatRoom, room_id)
    assert row is not None
    await replay.run_replay(client, capture, inputs, reps=1, budget=CallBudget(5), room=row, sink=records.append)

    assert [k["model"] for k in sent] == ["stat-model"]
    assert [k["config"].http_options.timeout for k in sent] == [replay.REPLAY_TIMEOUT_MS]
    assert [k["contents"] for k in sent] == [inputs[0].prompt]
    assert [k["config"].response_schema for k in sent] == [StatJudgmentResult]
    assert recorded == [("replay_stat_judgment", "stat-model")]
    (record,) = records
    assert (record["callSite"], record["sentModel"], record["error"]) == ("replay_stat_judgment", "stat-model", None)
    assert record["output"] == raw.model_dump()
    by_name = {s["name"]: s for s in record["statResult"]}
    assert by_name["세빈 호감도"] == {"statId": str(liking.entity_id), "name": "세빈 호감도", "start": 53.0, "requested": 28.0, "applied": 28.0}  # fmt: skip
    assert by_name["상영회까지"] == {"statId": str(days.entity_id), "name": "상영회까지", "start": 42.0, "requested": 45.0, "applied": 42.0}  # fmt: skip


# ── 스탯 줄 형식 비교 ────────────────────────────────────────────────────────


async def test_stat_formats_rewrite_only_the_stat_lines_or_append_the_baseline_sentence(
    db_client: httpx.AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    room_id, liking, days, fake, trace_path = await _played_stat_room(db_client, db_session, tmp_path, monkeypatch)
    start = replay.stat_start_from_trace(trace_path, room_id, 2)
    inputs = await replay.build_inputs(
        db_session, room_id, 2, kinds=["stat"], variant="full", stat_start=start, stat_formats=list(replay.STAT_FORMATS)
    )
    by_format = {i.stat_format: i.prompt for i in inputs}
    assert list(by_format) == ["current", "A", "L", "B"]
    assert by_format["current"] == fake.stat_prompts[1]  # 현행은 서버가 보낸 그대로

    # A: 현재값·범위가 이름 바로 뒤, 설명은 줄 끝. 프롬프트의 나머지는 한 글자도 다르지 않다.
    a = by_format["A"]
    assert f"- statId={liking.entity_id}, 이름=세빈 호감도, 현재값=53.0, 범위=[0, 100], 설명=하늘이 세빈의 일에 응하면 2~4 오른다." in a  # fmt: skip
    assert f"- statId={days.entity_id}, 이름=상영회까지, 현재값=42.0, 범위=[0, 42], 설명=날이 넘어가면 줄어든다.  ※ 감소만 할 수 있다. 한 턴에 최대 7까지 바뀐다." in a  # fmt: skip
    current = by_format["current"]
    head, tail = current.split(f"- statId={liking.entity_id}", 1)
    assert a.startswith(head)
    assert a.endswith(tail.split("\n", 2)[2])  # 스탯 두 줄 뒤(사용자 이름·이번 턴·지시문)는 같다
    assert len(a) == len(current)  # 같은 조각의 순서만 바뀐다

    # L: 현행 + 지시문 끝 한 문장. B: A + 같은 문장.
    assert by_format["L"] == current + " " + replay.BASELINE_SENTENCE
    assert by_format["B"] == a + " " + replay.BASELINE_SENTENCE
    assert all(i.call_site == "replay_stat_judgment" for i in inputs)


def test_stat_format_rewrite_stops_when_the_server_lines_are_not_found() -> None:
    # 서버 줄 형식이 바뀌어 복제한 현행 줄과 어긋나면, 엉뚱한 프롬프트를 보내지 않고 멈춘다.
    stat = StatDef(
        entity_id=uuid.uuid4(), starting_setup_id=uuid.uuid4(), name="호감", icon="heart", color="#ff0000",
        min_value=0, max_value=100, initial_value=50, unit=None, order=1, description="오른다.",
    )  # fmt: skip
    names = PromptNames(persona_name="하늘", default_user_name="", char_name=None)
    with pytest.raises(ValueError, match="스탯 줄"):
        replay.stat_prompt_variant("다른 형식의 프롬프트", [stat], {str(stat.entity_id): 50.0}, names, "A")
    assert replay.stat_prompt_variant("p", [stat], {}, names, "current") == "p"


async def test_stat_format_is_recorded_on_every_call(
    db_client: httpx.AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    room_id, liking, _days, _fake, trace_path = await _played_stat_room(db_client, db_session, tmp_path, monkeypatch)

    async def record_usage(*_: object) -> None:
        return None

    monkeypatch.setattr(gemini, "record_usage", record_usage)
    start = replay.stat_start_from_trace(trace_path, room_id, 2)
    inputs = await replay.build_inputs(
        db_session, room_id, 2, kinds=["stat"], variant="full", stat_start=start, stat_formats=["current", "B"]
    )
    raw = StatJudgmentResult(stat_changes=[StatChangeJudgment(stat_id=str(liking.entity_id), new_value=56)])
    sent: list[dict[str, Any]] = []

    async def generate_content(**kwargs: Any) -> SimpleNamespace:
        sent.append(kwargs)
        return SimpleNamespace(parsed=raw, usage_metadata=SimpleNamespace(prompt_token_count=1))

    client = GeminiLLMClient(api_key="test-key")
    monkeypatch.setattr(
        client,
        "_client",
        SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))),
    )
    capture: dict[str, Any] = {}
    replay.install_replay_transport(client, capture)
    records: list[dict[str, Any]] = []
    row = await db_session.get(ChatRoom, room_id)
    assert row is not None
    await replay.run_replay(client, capture, inputs, reps=2, budget=CallBudget(9), room=row, sink=records.append)
    assert [r["statFormat"] for r in records] == ["current", "current", "B", "B"]
    assert [k["contents"] for k in sent] == [inputs[0].prompt] * 2 + [inputs[1].prompt] * 2


async def test_stat_replay_judges_generation_replay_replies_with_overridden_definitions_in_the_main_line_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    room_id, _liking, days, _fake, trace_path = await _played_stat_room(db_client, db_session, tmp_path, monkeypatch)
    start = replay.stat_start_from_trace(trace_path, room_id, 2)
    gen = tmp_path / "gen.jsonl"
    gen.write_text(
        "\n".join(
            json.dumps(r, ensure_ascii=False)
            for r in (
                {"kind": "plan", "turn": 2},
                {
                    "kind": "call",
                    "turn": 2,
                    "variant": "supplement",
                    "rep": 0,
                    "reply": "이틀 뒤, 편집실.",
                    "error": None,
                },
                {"kind": "call", "turn": 2, "variant": "supplement", "rep": 1, "reply": "", "error": "Boom"},
                {"kind": "call", "turn": 2, "variant": "window", "rep": 0, "reply": "같은 날 밤.", "error": None},
            )
        ),
        encoding="utf-8",
    )
    replies = replay.replies_from_generation(gen, 2, "supplement")
    assert replies == [("gen:supplement:rep0", "이틀 뒤, 편집실.")]
    overrides = {"상영회까지": {"max_value": 46, "description": "보완판 설명. '사흘 뒤'면 3."}}
    (item,) = await replay.build_inputs(
        db_session,
        room_id,
        2,
        kinds=["stat"],
        variant="full",
        stat_start=start,
        stat_formats=["A"],
        assistant_messages=replies,
        stat_overrides=overrides,
    )
    assert item.source == "gen:supplement:rep0" and "이틀 뒤, 편집실." in item.prompt
    # 운영 main 의 줄 순서: statId → 이름 → 현재값 → 범위 → 설명 → 제약 꼬리.
    assert (
        f"- statId={days.entity_id}, 이름=상영회까지, 현재값=42.0, 범위=[0, 46], 설명=보완판 설명. '사흘 뒤'면 3."
        "  ※ 감소만 할 수 있다. 한 턴에 최대 7까지 바뀐다."
    ) in item.prompt
    assert [d.max_value for d in item.stat_defs] == [100, 46]
    await db_session.refresh(days)
    assert days.max_value == 42  # 원 행은 그대로
    with pytest.raises(ValueError, match="형식"):
        await replay.build_inputs(
            db_session, room_id, 2, kinds=["stat"], variant="full", stat_start=start, assistant_messages=replies
        )
    with pytest.raises(ValueError, match="없는 스탯"):
        replay.override_stat_defs(list(item.stat_defs), {"없는 스탯": {"max_value": 1}})
    path = tmp_path / "override.json"
    path.write_text(json.dumps({"stats": {"상영회까지": {"name": "x"}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="덮을 수 없는"):
        replay.load_stat_overrides(path)


async def test_stat_replay_judges_an_exchange_from_another_room_with_its_own_user_message(
    db_client: httpx.AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 운영 스모크 방의 한 턴처럼 격리 DB 에 없는 대화도, 측정 방의 스탯 정의를 빌려 같은 조립으로 판정한다.
    room_id, _liking, _days, fake, trace_path = await _played_stat_room(db_client, db_session, tmp_path, monkeypatch)
    start = replay.stat_start_from_trace(trace_path, room_id, 2)
    path = tmp_path / "exchange.json"
    path.write_text(
        json.dumps({"source": "smoke-t2", "user": "이틀 뒤 리허설 때 봬요.", "assistant": "그래, 오늘은 여기까지."}),
        encoding="utf-8",
    )
    user, reply = replay.load_exchange(path)
    assert reply == ("exchange:smoke-t2", "그래, 오늘은 여기까지.")
    (item,) = await replay.build_inputs(
        db_session,
        room_id,
        2,
        kinds=["stat"],
        variant="full",
        stat_start=start,
        stat_formats=["A"],
        assistant_messages=[reply],
        user_message=user,
    )
    assert "이틀 뒤 리허설 때 봬요." in item.prompt and "그래, 오늘은 여기까지." in item.prompt
    assert "벤치에 앉는다" not in item.prompt  # 측정 방의 그 턴 사용자 메시지는 싣지 않는다
    assert "벤치에 앉는다" in fake.stat_prompts[1]
    with pytest.raises(ValueError, match="응답도 함께"):
        await replay.build_inputs(
            db_session, room_id, 2, kinds=["stat"], variant="full", stat_start=start, user_message=user
        )
