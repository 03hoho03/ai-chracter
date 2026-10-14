"""사실 계층 — 키 정규화, 키별 최신(반증이 되살아나지 않음), 렌더 순서와 글자 상한, 시제품 추출(가짜 호출·가짜 SDK)."""

import asyncio
import json
import unicodedata
import uuid
from pathlib import Path
from typing import Any

import anthropic
import pytest

from api.db.models import ChatMessage, ChatMessageRole

from memory_eval import facts
from memory_eval.ledger import Ledger
from memory_eval.prototype_extract import Window
from memory_eval.prototype_facts import (
    FACT_CALL_SITE,
    FactStore,
    PrototypeFact,
    PrototypeFactResult,
    call_haiku,
    extract_next,
    extract_windows,
    fact_rows,
    load_fact_rows,
)


def _row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "fact",
        "subject": "민지",
        "object": None,
        "attribute": "생일",
        "value": "5월 3일",
        "truth_status": "confirmed",
        "asserted_by": "narration",
        "speaker": None,
        "known_by": None,
        "importance": 3,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- 키·최신·렌더


def test_fact_key_normalizes_case_composition_and_spacing_per_part() -> None:
    nfd = unicodedata.normalize("NFD", "민지")
    assert facts.fact_key("fact", f"  {nfd} ", "좋아하는   Movie") == facts.fact_key("fact", "민지", "좋아하는 movie")
    assert facts.fact_key("fact", "민지", "생일") != facts.fact_key("relation", "민지", "생일")
    assert facts.row_key(_row(kind="relation", object="태민", attribute="무시")) == "relation|민지|태민"


def test_latest_row_per_key_wins_and_keeps_write_order() -> None:
    rows = [
        _row(kind="relation", object="태민", attribute=None, value="서먹함"),
        _row(value="5월 3일"),
        _row(kind="relation", object="태민", attribute=None, value="믿음"),
    ]
    latest = facts.latest_by_key(rows)
    assert [r["value"] for r in latest] == ["5월 3일", "믿음"]
    assert [r["_order"] for r in latest] == [1, 2]


def test_a_refuted_value_is_not_revived_by_a_later_claim_but_a_correction_shows_the_new_value() -> None:
    revived = [
        _row(value="5월 3일", truth_status="claimed", speaker="태민"),
        _row(value="5월 3일", truth_status="disproved"),
        _row(value="5월 3일", truth_status="claimed", speaker="태민"),
    ]
    assert facts.latest_by_key(revived)[0]["truth_status"] == "disproved"
    corrected = [_row(value="5월 3일", truth_status="disproved"), _row(value="6월 9일", truth_status="confirmed")]
    assert facts.latest_by_key(corrected)[0]["value"] == "6월 9일"


def test_render_order_is_relations_then_known_by_then_refuted_then_others_by_importance_then_recency() -> None:
    rows = [
        _row(attribute="취미", value="낚시", importance=2),
        _row(attribute="비밀", value="전학", known_by=["사용자"], importance=1),
        _row(attribute="고향", value="부산", truth_status="disproved", importance=5),
        _row(attribute="혈액형", value="A", importance=4),
        _row(attribute="별명", value="곰", importance=2),
        _row(kind="relation", object="태민", attribute=None, value="질투", importance=1),
    ]
    kept, dropped, _ = facts.render(rows, max_chars=10_000)
    assert [r["value"] for r in kept] == ["질투", "전학", "부산", "A", "곰", "낚시"]
    assert dropped == []


def test_render_stops_at_the_first_line_that_would_pass_the_cap_and_drops_the_rest() -> None:
    rows = [_row(attribute=f"속성{i}", value="가" * 40, importance=5 - i) for i in range(5)]
    one = len(facts.render_line(facts.latest_by_key(rows)[0]))
    kept, dropped, text = facts.render(rows, max_chars=one * 2 + 1)
    assert len(kept) == 2 and len(dropped) == 3
    assert len(text) == one * 2 + 1
    kept_short, dropped_short, _ = facts.render(rows, max_chars=one * 2)
    assert len(kept_short) == 1 and len(dropped_short) == 4


def test_render_line_marks_claims_refutations_and_who_knows() -> None:
    assert facts.render_line(_row(truth_status="claimed", speaker="태민")).endswith("(주장 — 태민)")
    assert facts.render_line(_row(truth_status="disproved")).endswith("(사실 아님)")
    assert facts.render_line(_row(known_by=["사용자", "민지"])).endswith("(아는 사람: 사용자, 민지)")
    assert facts.render_line(_row(kind="relation", object="태민", value="믿음")) == "- 민지 → 태민: 믿음"


def test_existing_key_lines_keep_only_the_latest_per_key_and_the_most_recent_limit() -> None:
    rows = [_row(attribute=f"속성{i}", value=str(i)) for i in range(5)] + [_row(attribute="속성0", value="새 값")]
    lines = facts.existing_key_lines(rows, limit=3)
    assert lines == [
        "fact|민지|속성3 = 3 (confirmed)",
        "fact|민지|속성4 = 4 (confirmed)",
        "fact|민지|속성0 = 새 값 (confirmed)",
    ]


# ---------------------------------------------------------------- 시제품 추출


def _window(snapshot: uuid.UUID, *, turn_before: int = 0, fold_turn: int = 40) -> Window:
    messages = [
        ChatMessage(role=ChatMessageRole.USER, content="u1"),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="a1"),
        ChatMessage(role=ChatMessageRole.USER, content="u2"),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="a2"),
    ]
    return Window(snapshot_id=snapshot, messages=messages, turn_before=turn_before, fold_turn=fold_turn)


def _fact(**overrides: Any) -> PrototypeFact:
    base: dict[str, Any] = {
        "kind": "fact",
        "subject": "민지",
        "object": "무시될 대상",
        "attribute": "생일",
        "value": "5월 3일",
        "truth_status": "claimed",
        "asserted_by": "character",
        "speaker": "태민",
        "known_by": [],
        "importance": 9,
        "start_line": 4,
        "end_line": 2,
    }
    base.update(overrides)
    return PrototypeFact.model_validate(base)


def test_fact_rows_normalize_the_key_drop_off_kind_fields_clamp_and_map_lines_to_turns() -> None:
    window = _window(uuid.uuid4(), turn_before=10, fold_turn=40)
    result = PrototypeFactResult(
        facts=[_fact(), _fact(subject=" "), _fact(kind="relation", object="태민", known_by=["사용자", " "])]
    )
    rows = fact_rows(window, result, version="v1")
    assert len(rows) == 2
    first, second = rows
    assert first["object"] is None and first["attribute"] == "생일"
    assert first["fact_key"] == "fact|민지|생일"
    assert first["importance"] == 5 and first["known_by"] is None and first["speaker"] == "태민"
    assert (first["start_turn"], first["end_turn"]) == (11, 12)  # 뒤집힌 줄 4~2 → 2~4 → 턴 11 의 응답 줄부터 턴 12 까지
    assert first["available_from_turn"] == 41
    assert second["attribute"] is None and second["object"] == "태민" and second["known_by"] == ["사용자"]


def test_fact_rows_map_reversed_lines_through_the_window_turns() -> None:
    window = _window(uuid.uuid4(), turn_before=10)
    rows = fact_rows(window, PrototypeFactResult(facts=[_fact(start_line=1, end_line=2)]), version="v1")
    assert (rows[0]["start_turn"], rows[0]["end_turn"]) == (11, 11)


def test_each_window_gets_the_earlier_windows_latest_keys_as_input() -> None:
    windows = [_window(uuid.uuid4()), _window(uuid.uuid4())]
    prompts: list[str] = []

    async def caller(prompt: str) -> PrototypeFactResult:
        prompts.append(prompt)
        return PrototypeFactResult(facts=[_fact(value=f"값{len(prompts)}", truth_status="confirmed")])

    rows = asyncio.run(
        extract_windows(
            windows, render=lambda w: "[1] 대화", caller=caller, instruction="지시", user_name="나", version="v1"
        )
    )
    assert len(rows) == 2
    assert "[기존 키]\n(없음)" in prompts[0]
    assert "fact|민지|생일 = 값1 (confirmed)" in prompts[1]
    assert prompts[0].startswith("지시\n\n사용자의 이야기 속 이름: 나")


def test_store_catch_up_extracts_the_oldest_pending_window_once_per_call(tmp_path: Path) -> None:
    windows = [_window(uuid.uuid4()), _window(uuid.uuid4())]
    store = FactStore(tmp_path / "facts-s8.jsonl")
    seen: list[str] = []

    async def caller(prompt: str) -> PrototypeFactResult:
        seen.append(prompt)
        return PrototypeFactResult(facts=[_fact(value=f"값{len(seen)}")])

    def step() -> bool:
        return asyncio.run(
            extract_next(
                windows, store, render=lambda w: "x", caller=caller, instruction="i", user_name="u", version="v"
            )
        )

    assert step() is True
    assert store.done_ids() == {str(windows[0].snapshot_id)}
    assert step() is True
    assert "값1" in seen[1]
    assert step() is False
    assert len(seen) == 2
    assert [r["value"] for r in load_fact_rows(store.path)] == ["값1", "값2"]


def test_load_fact_rows_reads_the_json_array_output(tmp_path: Path) -> None:
    path = tmp_path / "facts.json"
    path.write_text(json.dumps([_row()], ensure_ascii=False), encoding="utf-8")
    assert load_fact_rows(path) == [_row()]


class _FakeMessages:
    def __init__(self, sent: list[dict[str, Any]], body: str) -> None:
        self.sent = sent
        self.body = body

    async def create(self, **kwargs: Any) -> anthropic.types.Message:
        self.sent.append(kwargs)
        return anthropic.types.Message.model_validate(
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": kwargs["model"],
                "content": [{"type": "text", "text": self.body}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1_000, "output_tokens": 200, "cache_read_input_tokens": 100},
            }
        )


def test_direct_haiku_call_turns_thinking_off_uses_low_effort_and_writes_the_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sent: list[dict[str, Any]] = []
    body = PrototypeFactResult(facts=[_fact()]).model_dump_json()

    class FakeClient:
        def __init__(self, *, api_key: str) -> None:
            assert api_key == "sk-test"
            self.messages = _FakeMessages(sent, body)

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeClient)
    book = Ledger(tmp_path / "ledger.jsonl")
    result = asyncio.run(call_haiku("sk-test", "프롬프트", book, stage="facts-v1"))
    assert result.facts[0].value == "5월 3일"
    assert sent[0]["model"] == "claude-haiku-5-5"
    assert sent[0]["thinking"] == {"type": "disabled"}
    assert sent[0]["output_config"]["effort"] == "low"
    (row,) = book.rows()
    assert row["callSite"] == FACT_CALL_SITE and row["stage"] == "facts-v1"
    assert (row["inputTokens"], row["cachedTokens"], row["outputTokens"]) == (1_100, 100, 200)
    assert row["costUsd"] > 0


def test_direct_haiku_call_refuses_without_a_key(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="키"):
        asyncio.run(call_haiku("", "p", Ledger(tmp_path / "ledger.jsonl"), stage="s"))
