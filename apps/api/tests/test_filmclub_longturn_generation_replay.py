"""생성 리플레이 도구를 LLM 없이 본다 — 윈도 입력이 그 턴 당시 요약으로 윈도를 씌우는지, 전체 입력이 원문을 다 싣고
요약을 빼는지, 기억 노트를 그 턴 값으로 바꿔 끼워도 DB 는 그대로인지, 호출이 리플레이 라벨·생성 모델·생성 설정으로
나가고 상한을 지키는지."""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.chat import ChatMessage, ChatRoom, ChatRoomMemorySnapshot
from api.db.models.story import StoryVersionDetail
from api.llm import gemini
from api.llm.gemini import GeminiLLMClient
from api.llm.pricing import estimate_cost_usd
from experiments.filmclub_longturn import build_swap_tables, supplement_swap
from experiments.filmclub_longturn import generation_replay as replay
from experiments.filmclub_longturn.replay_budget import UNKNOWN_CALL_USD, CallBudget, ledger_paths, sum_ledger
from experiments.filmclub_longturn.supplement_swap import SwapSlot, check_swap, load_swap_table
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
    # 드라이버는 노트가 바뀐 턴에만 스냅샷을 남긴다 — 그 사이 턴은 앞 스냅샷의 노트였다.
    assert replay.note_for_turn(snaps, room_id, 6) == "노트"
    with pytest.raises(ValueError, match="이하"):
        replay.note_for_turn(snaps, room_id, 4)


def test_note_for_turn_picks_the_latest_snapshot_at_or_before_the_turn(tmp_path: Path) -> None:
    room_id = uuid.uuid4()
    snaps = tmp_path / "snaps.jsonl"
    snaps.write_text(
        "\n".join(
            f'{{"kind": "memorySnapshot", "roomId": "{room}", "turn": {turn}, "note": "{note}"}}'
            for room, turn, note in ((room_id, 1, "1턴"), (room_id, 7, "7턴"), (uuid.uuid4(), 9, "다른 방"))
        ),
        encoding="utf-8",
    )
    assert [replay.note_for_turn(snaps, room_id, t) for t in (1, 6, 7, 30)] == ["1턴", "1턴", "7턴", "7턴"]


def test_stats_before_turn_rolls_affection_back_by_that_turns_change(tmp_path: Path) -> None:
    room_id = uuid.uuid4()
    snaps = tmp_path / "snaps.jsonl"
    stats = [{"id": "d", "name": "도희 호감도"}, {"id": "c", "name": "상영회까지"}]
    static = {"kind": "roomStatic", "roomId": str(room_id), "stats": stats}
    snaps.write_text(json.dumps(static) + "\n" + json.dumps(static) + "\n", encoding="utf-8")
    ids = replay.stat_ids_by_name(snaps, room_id)
    assert ids == {"도희 호감도": "d", "상영회까지": "c"}
    turns = tmp_path / "turns.json"
    row = {
        "turn": 3,
        "countdownBefore": 40.0,
        "affection": {"도희 호감도": 57.0},
        "affectionDelta": {"도희 호감도": 3.0},
    }
    turns.write_text(json.dumps([row]), encoding="utf-8")
    # 생성은 판정 앞이다 — 호감은 판정 뒤 값에서 그 턴 변화를 뺀 값, 게이지는 판정 전 값.
    assert replay.stats_before_turn(turns, ids, 3) == {"d": 54.0, "c": 40.0}
    with pytest.raises(ValueError, match="턴 4"):
        replay.stats_before_turn(turns, ids, 4)
    other = static | {"stats": [{"id": "x", "name": "도희 호감도"}]}
    snaps.write_text(json.dumps(static) + "\n" + json.dumps(other) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="다르다"):
        replay.stat_ids_by_name(snaps, room_id)


async def test_supplement_in_memory_swaps_only_the_table_text_and_leaves_the_rows_alone(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _room_with_summary(db_client, db_session)
    slot = SwapSlot(key="설정", v6fix="세계관 설정", supplement="보완판 세계관", when="always")
    inputs = await replay.build_generation_inputs(
        db_session, room.room_id, 10, variants=["window", "supplement"], swap=replay.SwapSpec([slot])
    )
    window, supplement = inputs
    assert "세계관 설정" in window.prompt and "보완판 세계관" not in window.prompt
    assert "보완판 세계관" in supplement.prompt and "세계관 설정" not in supplement.prompt
    result = check_swap(
        base_prompt=window.prompt,
        base_system=window.system_instruction,
        swapped_prompt=supplement.prompt,
        swapped_system=supplement.system_instruction,
        slots=[slot],
        situation_notes=[],
        keyword_notes=[],
    )
    assert result["passed"] and result["swapCounts"] == {"설정": 1}
    await db_session.commit()
    db_session.expire_all()
    detail = (await db_session.scalars(select(StoryVersionDetail))).all()
    assert detail and all(row.setting_text != "보완판 세계관" for row in detail)
    # 이어서 만든 v6-fix 입력에도 바꾼 글이 남지 않는다(메모리 안 치환을 되돌렸다).
    (again,) = await replay.build_generation_inputs(db_session, room.room_id, 10, variants=["window"])
    assert again.prompt == window.prompt
    with pytest.raises(ValueError, match="찾지 못한"):
        await replay.build_generation_inputs(
            db_session,
            room.room_id,
            10,
            variants=["window", "supplement"],
            swap=replay.SwapSpec([SwapSlot(key="없음", v6fix="작품에 없는 글", supplement="x", when="always")]),
        )


def _slots() -> list[SwapSlot]:
    return [
        SwapSlot(key="무대", v6fix="사흘 뒤처럼", supplement="다음 날·이틀 뒤처럼", when="always"),
        SwapSlot(key="직전", v6fix="일주일도 안 남았다.", supplement="코앞이다.", when="situationNote:상영회 직전"),
    ]


def _check(
    swapped: str, slots: list[SwapSlot], notes: list[str], base: str = "[무대] 사흘 뒤처럼 적는다. [대화]"
) -> Any:
    return check_swap(
        base_prompt=base,
        base_system="s",
        swapped_prompt=swapped,
        swapped_system="s",
        slots=slots,
        situation_notes=notes,
        keyword_notes=[],
    )


def test_swap_check_passes_only_when_every_due_slot_was_swapped_and_nothing_else_changed() -> None:
    swapped = "[무대] 다음 날·이틀 뒤처럼 적는다. [대화]"
    ok = _check(swapped, _slots(), [])
    assert ok["passed"] and ok["expectedSlots"] == ["무대"] and ok["swapCounts"] == {"무대": 1, "직전": 0}
    # 덜 바꿔 끼움 — 역치환은 통과하지만 양성 단언이 잡는다.
    under = _check("[무대] 사흘 뒤처럼 적는다. [대화]", _slots(), [])
    assert under["reverseIdentical"] and under["missingSlots"] == ["무대"] and not under["passed"]
    # 표 밖 변경 — 역치환이 잡는다.
    extra = _check("[무대] 다음 날·이틀 뒤처럼 적는다. [대화!]", _slots(), [])
    assert not extra["reverseIdentical"] and not extra["passed"] and extra["firstDifferenceAt"] == 20
    # 실림 조건이 틀림 — 분석표는 직전 노트가 실렸다는데 v6-fix 프롬프트엔 없다.
    wrong = _check(swapped, _slots(), ["상영회 직전"])
    assert wrong["conditionMismatch"] == ["직전"] and wrong["missingSlots"] == ["직전"] and not wrong["passed"]
    # 실리지 말아야 할 칸이 실림.
    base = "[무대] 사흘 뒤처럼 적는다. 일주일도 안 남았다. [대화]"
    leaked = _check("[무대] 다음 날·이틀 뒤처럼 적는다. 코앞이다. [대화]", _slots(), [], base=base)
    assert leaked["unexpectedSlots"] == ["직전"] and not leaked["passed"]


def test_swap_check_fails_when_only_one_of_two_places_of_the_same_text_was_swapped() -> None:
    # 같은 v6-fix 조각이 두 자리에 실렸는데 한 자리만 바뀌었다 — 되돌리면 같아지고(역치환) 보완판 조각도 한 번은 있어서
    # (양성) 앞의 두 겹은 통과한다. 개수 단언과 잔존 단언이 잡는다.
    base = "[무대] 사흘 뒤처럼 적는다. [예시] 사흘 뒤처럼 적는다. [대화]"
    half = _check("[무대] 다음 날·이틀 뒤처럼 적는다. [예시] 사흘 뒤처럼 적는다. [대화]", _slots(), [], base=base)
    assert half["reverseIdentical"] and not half["missingSlots"]
    assert half["countMismatch"] == ["무대"] and half["v6fixLeftover"] == {"무대": 1} and not half["passed"]
    full = _check(
        "[무대] 다음 날·이틀 뒤처럼 적는다. [예시] 다음 날·이틀 뒤처럼 적는다. [대화]", _slots(), [], base=base
    )
    assert full["passed"] and full["baseCounts"]["무대"] == full["swapCounts"]["무대"] == 2


def test_unique_fragment_residue_counts_history_copies_and_catches_old_text_outside_the_slot() -> None:
    slot = SwapSlot(key="규칙", v6fix="시간 | 요일과 때", supplement="시간 | 날짜·요일과 때", when="always")
    # 고유 조각은 끼워 넣기 자리의 앞뒤 글자로 만들고, 보완판 문안에는 없다.
    (fragment,) = supplement_swap.unique_fragments(slot.v6fix, slot.supplement)
    assert fragment in slot.v6fix and fragment not in slot.supplement
    # 대화 기록에 v6-fix 와 같은 말이 원래 있으면 셈에 들어가 통과한다.
    base = "[규칙] 시간 | 요일과 때 [대화] 시간 | 요일과 때"
    ok = check_swap(
        base_prompt=base,
        base_system="s",
        swapped_prompt="[규칙] 시간 | 날짜·요일과 때 [대화] 시간 | 요일과 때",
        swapped_system="s",
        slots=[slot],
        situation_notes=[],
        keyword_notes=[],
    )
    assert ok["swapCounts"] == {"규칙": 1} and ok["countMismatch"] == ["규칙"] and not ok["passed"]


def test_prompt_form_lets_the_check_compare_author_text_with_the_rendered_prompt() -> None:
    slot = SwapSlot(key="설정", v6fix="{{user}}의 사흘 뒤", supplement="{{user}}의 다음 날", when="always")
    result = check_swap(
        base_prompt="[설정] 하늘의 사흘 뒤",
        base_system="s",
        swapped_prompt="[설정] 하늘의 다음 날",
        swapped_system="s",
        slots=[slot],
        situation_notes=[],
        keyword_notes=[],
        prompt_form=lambda text: text.replace("{{user}}", "하늘"),
    )
    assert result["passed"]


async def test_supplement_swaps_the_history_opening_and_restores_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _room_with_summary(db_client, db_session)
    (window,) = await replay.build_generation_inputs(db_session, room.room_id, 10, variants=["window"])
    opening = (
        await db_session.scalars(
            select(ChatMessage).where(ChatMessage.chat_room_id == room.room_id).order_by(ChatMessage.created_at)
        )
    ).first()
    assert opening is not None and opening.content in window.prompt
    slot = SwapSlot(
        key="오프닝", v6fix=opening.content, supplement="보완판 오프닝 9월 22일", when="always", target="historyOpening"
    )
    window, supplement = await replay.build_generation_inputs(
        db_session, room.room_id, 10, variants=["window", "supplement"], swap=replay.SwapSpec([slot])
    )
    assert "보완판 오프닝 9월 22일" in supplement.prompt and opening.content not in supplement.prompt
    result = check_swap(
        base_prompt=window.prompt,
        base_system=window.system_instruction,
        swapped_prompt=supplement.prompt,
        swapped_system=supplement.system_instruction,
        slots=[slot],
        situation_notes=[],
        keyword_notes=[],
        prompt_form=window.prompt_form,
    )
    assert result["passed"], result
    await db_session.refresh(opening)
    assert opening.content == slot.v6fix
    (again,) = await replay.build_generation_inputs(db_session, room.room_id, 10, variants=["window"])
    assert again.prompt == window.prompt
    with pytest.raises(ValueError, match="다르다"):
        await replay.build_generation_inputs(
            db_session,
            room.room_id,
            10,
            variants=["window", "supplement"],
            swap=replay.SwapSpec(
                [SwapSlot(key="o", v6fix="다른 오프닝", supplement="x", when="always", target="historyOpening")]
            ),
        )


def test_build_swap_tables_gives_n_its_own_stage_text_and_marks_the_opening() -> None:
    cell = {"v6fix_text": "v", "supplement_text_W": "w", "loaded": "always"}
    source = {
        "variants": {"W": "w안", "N": "n안"},
        "slots": [
            {**cell, "key": "setting_text", "supplement_text_N": "n"},
            {**cell, "key": "opening_message"},
            {**cell, "key": "same", "supplement_text_W": "v"},
        ],
    }
    tables = build_swap_tables.build_tables(source)
    assert [s["supplement"] for s in tables["W"]["slots"]] == ["w", "w"]
    assert [s["supplement"] for s in tables["N"]["slots"]] == ["n", "w"]
    assert [s["target"] for s in tables["N"]["slots"]] == ["rows", "historyOpening"]


def test_swap_table_rejects_duplicate_keys_unchanged_text_and_unknown_conditions(tmp_path: Path) -> None:
    path = tmp_path / "table.json"
    for slots, message in (
        ([{"key": "a", "v6fix": "x", "supplement": "y", "when": "always"}] * 2, "같은 칸"),
        ([{"key": "a", "v6fix": "x", "supplement": "x", "when": "always"}], "같다"),
        ([{"key": "a", "v6fix": "x", "supplement": "y", "when": "stat:상영회까지"}], "모른다"),
    ):
        path.write_text(json.dumps({"slots": slots}), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            load_swap_table(path)


def test_budget_stops_on_calls_or_on_actual_cost_including_the_ledger(tmp_path: Path) -> None:
    budget = CallBudget(5, usd_limit=0.01, spent_usd=0.004)
    assert budget.take()
    budget.charge({"costUsd": 0.005})
    assert budget.take()
    budget.charge({"costUsd": 0.002})  # 누적 0.011 ≥ 0.01
    assert not budget.take() and budget.used == 2
    unknown = CallBudget(5, usd_limit=0.015)
    assert unknown.take()
    unknown.charge({"costUsd": None})  # 원가를 모르면 넉넉히 센다
    assert unknown.spent_usd == UNKNOWN_CALL_USD
    ledger = tmp_path / "a" / "gen.jsonl"
    ledger.parent.mkdir()
    ledger.write_text(
        "\n".join(
            json.dumps(r)
            for r in ({"kind": "plan"}, {"kind": "call", "costUsd": 0.002}, {"kind": "call", "costUsd": None})
        ),
        encoding="utf-8",
    )
    total = sum_ledger(ledger_paths(str(tmp_path / "**" / "*.jsonl")))
    assert (total.calls, total.unknown_calls) == (2, 1)
    assert total.charged_usd == pytest.approx(0.002 + UNKNOWN_CALL_USD)


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
        client, capture, inputs, reps=2, budget=CallBudget(3), room=row, sink=records.append
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
