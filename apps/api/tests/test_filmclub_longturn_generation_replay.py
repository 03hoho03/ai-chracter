"""생성 리플레이 도구를 LLM 없이 본다 — 윈도 입력이 그 턴 당시 요약으로 윈도를 씌우는지, 전체 입력이 원문을 다 싣고
요약을 빼는지, 기억 노트를 그 턴 값으로 바꿔 끼워도 DB 는 그대로인지, 호출이 리플레이 라벨·생성 모델·생성 설정으로
나가고 상한을 지키는지."""

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.chat import ChatRoom, ChatRoomMemorySnapshot
from api.llm import gemini
from api.llm.gemini import GeminiLLMClient
from api.llm.pricing import estimate_cost_usd
from experiments.filmclub_longturn import generation_replay as replay
from factories import Room, _open_room


async def _room_with_summary(db_client: httpx.AsyncClient, db_session: AsyncSession) -> Room:
    """12턴 스토리 방 — 턴 4까지 덮는 요약을 턴 6 응답 직후에, 턴 8까지 덮는 요약을 마지막 턴 뒤에 만든다."""
    room = await _open_room(db_client, db_session, turns=12, lane="story")
    for cursor_turn, made_after_turn, text in ((4, 6, "4턴까지의 요약"), (8, 12, "8턴까지의 요약")):
        db_session.add(
            ChatRoomMemorySnapshot(
                chat_room_id=room.room_id,
                cursor_created_at=room.turns[cursor_turn][1].created_at,
                cursor_message_id=room.turns[cursor_turn][1].id,
                summary_text=text,
                source="auto",
                created_at=room.turns[made_after_turn][1].created_at + timedelta(milliseconds=500),
            )
        )
    await db_session.commit()
    return room


async def test_window_input_uses_the_summary_that_existed_at_that_turn_and_full_input_has_every_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _room_with_summary(db_client, db_session)
    before = settings.memory_window_generation
    inputs = await replay.build_generation_inputs(db_session, room.room_id, 10, variants=["window", "full"])
    window, full = inputs
    assert [(i.variant, i.call_site) for i in inputs] == [("window", "replay_generate"), ("full", "replay_generate")]
    # 윈도: 턴 10 때 있던 요약은 턴 4 까지 — 턴 8 요약은 그 뒤에 생겼다.
    assert "4턴까지의 요약" in window.prompt and "8턴까지의 요약" not in window.prompt
    assert "[U04]" not in window.prompt and "[U05]" in window.prompt
    assert window.history_messages == 1 + 2 * 5  # 오프닝 + 턴 5~9
    # 전체: 원문 전부, 요약은 싣지 않는다(앱의 윈도 꺼짐 조립).
    assert "[U01]" in full.prompt and "[A09]" in full.prompt
    assert "4턴까지의 요약" not in full.prompt
    assert full.history_messages == 1 + 2 * 9
    for item in inputs:
        assert "[U10]" in item.prompt and "[A10]" not in item.prompt  # 그 턴 사용자 메시지까지, 응답은 없다
        assert item.system_instruction
        assert item.user_label
    assert settings.memory_window_generation == before


async def test_memory_note_override_reaches_the_prompt_without_touching_the_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _room_with_summary(db_client, db_session)
    note = "그 턴 당시의 기억 노트 — 렌즈 케이스"
    inputs = await replay.build_generation_inputs(
        db_session, room.room_id, 10, variants=["window", "full"], memory_note=note
    )
    assert all(note in item.prompt for item in inputs)
    await db_session.commit()
    db_session.expire_all()
    row = await db_session.get(ChatRoom, room.room_id)
    assert row is not None and row.memory_note != note


def test_dump_and_note_lookups_pick_that_room_and_turn(tmp_path: Path) -> None:
    room_id = uuid.uuid4()
    dump = tmp_path / "dump.jsonl"
    dump.write_text(
        "\n".join(
            [
                f'{{"roomId": "{room_id}", "turn": 5, "systemInstruction": "s", "prompt": "옛 시도"}}',
                f'{{"roomId": "{uuid.uuid4()}", "turn": 5, "systemInstruction": "s", "prompt": "다른 방"}}',
                f'{{"roomId": "{room_id}", "turn": 5, "systemInstruction": "s", "prompt": "마지막 시도"}}',
            ]
        ),
        encoding="utf-8",
    )
    record, count = replay.dump_record(dump, room_id, 5)
    assert record["prompt"] == "마지막 시도" and count == 2
    snaps = tmp_path / "snaps.jsonl"
    snaps.write_text(
        f'{{"kind": "memorySnapshot", "roomId": "{room_id}", "turn": 5, "note": "노트"}}\n'
        f'{{"kind": "pause", "roomId": "{room_id}"}}\n',
        encoding="utf-8",
    )
    assert replay.note_for_turn(snaps, room_id, 5) == "노트"
    with pytest.raises(ValueError):
        replay.note_for_turn(snaps, room_id, 6)


def _fake_stream_client(monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]) -> GeminiLLMClient:
    async def generate_content_stream(**kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        sent.append(kwargs)

        async def chunks() -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(text="렌즈 ", candidates=[], usage_metadata=None, prompt_feedback=None)
            yield SimpleNamespace(
                text="케이스요",
                candidates=[SimpleNamespace(finish_reason="STOP")],
                usage_metadata=SimpleNamespace(
                    prompt_token_count=100,
                    cached_content_token_count=0,
                    candidates_token_count=7,
                    thoughts_token_count=3,
                    total_token_count=110,
                ),
                prompt_feedback=None,
            )

        return chunks()

    client = GeminiLLMClient(api_key="test-key")
    monkeypatch.setattr(
        client,
        "_client",
        SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=generate_content_stream))),
    )
    return client


async def test_replay_calls_go_out_with_the_replay_label_generation_model_and_settings(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = await _room_with_summary(db_client, db_session)
    inputs = await replay.build_generation_inputs(db_session, room.room_id, 10, variants=["window", "full"])
    recorded: list[tuple[str, str]] = []

    async def record_usage(call_site: str, model: str, usage: object) -> None:
        recorded.append((call_site, model))

    monkeypatch.setattr(gemini, "record_usage", record_usage)
    sent: list[dict[str, Any]] = []
    client = _fake_stream_client(monkeypatch, sent)
    capture: dict[str, Any] = {}
    replay.install_stream_capture(client, capture)
    row = await db_session.get(ChatRoom, room.room_id)
    assert row is not None
    records: list[dict[str, Any]] = []
    await replay.run_generation_replay(
        client, capture, inputs, reps=2, budget=replay.CallBudget(3), room=row, sink=records.append
    )
    calls = [r for r in records if r["kind"] == "call"]
    assert [c["variant"] for c in calls] == ["window", "window", "full"]
    assert records[-1]["kind"] == "budgetExhausted"
    assert recorded == [("replay_generate", settings.gemini_model_name)] * 3
    assert all(kw["model"] == settings.gemini_model_name for kw in sent)
    assert sent[0]["contents"] == inputs[0].prompt and sent[2]["contents"] == inputs[1].prompt
    config = sent[0]["config"]
    assert config.system_instruction == inputs[0].system_instruction
    assert config.stop_sequences == [f"\n{inputs[0].user_label}:"]
    assert config.max_output_tokens == settings.gemini_max_output_tokens
    assert config.http_options.timeout == settings.gemini_generate_timeout_ms  # 생성과 같은 설정
    assert calls[0]["reply"] == "렌즈 케이스요"
    assert calls[0]["tokens"]["prompt"] == 100 and calls[0]["finishReason"] == "STOP"
    assert calls[0]["costUsd"] == estimate_cost_usd(
        settings.gemini_model_name, input_tokens=100, cached_tokens=0, output_tokens=7, thoughts_tokens=3
    )
