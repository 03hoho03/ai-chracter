"""넣기의 사실 추출 따라잡기 — 운영 모듈이 있으면 그것, 없으면 시제품을 고르는 어댑터, 시제품 따라잡기의 진전·실패 세기,
되감기 준비가 사실 추출 완료까지 기다리는지."""

import asyncio
import sys
import types
import uuid
from pathlib import Path
from typing import Any, cast

import pytest

from api.db.models import ChatMessage, ChatMessageRole

from memory_eval import fact_catchup
from memory_eval.fact_catchup import LoadedWindows, OperationalFacts, PrototypeFacts, fact_catch_up
from memory_eval.fake_llm import FakeMemoryLLM
from memory_eval.insert import RewindState, ensure_rewind_ready, plan, rewind_ready
from memory_eval.ledger import BudgetExceededError
from memory_eval.plants import PlantSet
from memory_eval.prototype_extract import Window
from memory_eval.prototype_facts import FactStore, PrototypeFact, PrototypeFactResult

_NO_DB: Any = object()


def _state(facts_status: str | None, *, status: str | None = "done", episodes: int | None = 1) -> RewindState:
    return RewindState(
        snapshot_id="s1", extraction_status=status, covering_episodes=episodes, facts_status=facts_status
    )


# ---------------------------------------------------------------- 되감기 준비


def test_fact_run_waits_for_the_snapshot_facts_even_without_scene_extraction() -> None:
    assert not rewind_ready(_state(None, status=None, episodes=None), extract=False, facts=True)
    assert rewind_ready(_state("done", status=None, episodes=None), extract=False, facts=True)


def test_scene_and_fact_runs_need_both_done() -> None:
    assert not rewind_ready(_state("done", status="running"), extract=True, facts=True)
    assert not rewind_ready(_state("failed"), extract=True, facts=True)
    assert rewind_ready(_state("done"), extract=True, facts=True)
    assert rewind_ready(_state(None), extract=True, facts=False)


def test_rewind_catch_up_keeps_extracting_until_the_facts_are_done() -> None:
    states = iter([_state(None), _state(None), _state("done")])
    calls: list[str] = []

    async def read() -> RewindState:
        return next(states)

    async def extract() -> None:
        calls.append("extract")

    final = asyncio.run(ensure_rewind_ready(read, extract, extract_enabled=True, attempts=3, facts_enabled=True))
    assert final.facts_status == "done"
    assert calls == ["extract", "extract"]


def test_plan_counts_one_more_call_per_fold_when_facts_are_extracted() -> None:
    plant_set = PlantSet(raw={}, plants=[], abstains=[])
    scenes = plan(plant_set, start_turn=1, until_turn=50, freeze_at=[], extract=True)
    both = plan(plant_set, start_turn=1, until_turn=50, freeze_at=[], extract=True, extract_facts=True)
    assert len(scenes["nominalFoldTurns"]) == 3
    assert (scenes["llmCalls"], both["llmCalls"]) == (6, 9)


# ---------------------------------------------------------------- 어댑터 선택


async def _empty(prompt: str) -> PrototypeFactResult:
    return PrototypeFactResult(facts=[])


def test_adapter_uses_the_operational_module_when_it_exists(tmp_path: Path) -> None:
    module = types.ModuleType("fake_memory_facts")
    chosen = fact_catch_up(
        FakeMemoryLLM(),
        store=FactStore(tmp_path / "f.jsonl"),
        caller=_empty,
        instruction="i",
        version="v1",
        find_module=lambda: module,
    )
    assert isinstance(chosen, OperationalFacts) and chosen.module is module


def test_adapter_falls_back_to_the_prototype_and_needs_its_instruction(tmp_path: Path) -> None:
    store = FactStore(tmp_path / "f.jsonl")
    chosen = fact_catch_up(
        FakeMemoryLLM(), store=store, caller=_empty, instruction="i", version="v1", find_module=lambda: None
    )
    assert isinstance(chosen, PrototypeFacts) and chosen.store is store
    with pytest.raises(SystemExit, match="문안"):
        fact_catch_up(
            FakeMemoryLLM(), store=store, caller=_empty, instruction=None, version="v1", find_module=lambda: None
        )


def test_operational_module_lookup_returns_none_only_when_the_module_itself_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fact_catchup, "OPERATIONAL_MODULE", "api.chat.memory_facts_missing_in_this_test")
    assert fact_catchup.operational_module() is None
    name = "memory_eval_test_fake_facts"
    monkeypatch.setattr(fact_catchup, "OPERATIONAL_MODULE", name)
    without = types.ModuleType(name)
    monkeypatch.setitem(sys.modules, name, without)
    with pytest.raises(SystemExit, match="extract_pending_facts"):
        fact_catchup.operational_module()

    async def extract_pending_facts(*args: Any, **kwargs: Any) -> None:
        return None

    without.extract_pending_facts = extract_pending_facts  # type: ignore[attr-defined]
    assert fact_catchup.operational_module() is without


def test_fake_llm_answers_a_facts_schema_with_no_facts() -> None:
    from api.llm.client import LLMCallContext

    result = asyncio.run(
        FakeMemoryLLM().generate_structured(
            "p", PrototypeFactResult, usage=LLMCallContext("chat_memory_episode", None, None)
        )
    )
    assert result.facts == []


# ---------------------------------------------------------------- 시제품 따라잡기


def _window() -> Window:
    messages = [
        ChatMessage(role=ChatMessageRole.USER, content="u"),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="a"),
    ]
    return Window(snapshot_id=uuid.uuid4(), messages=messages, turn_before=0, fold_turn=30)


def _prototype(tmp_path: Path, caller: Any, windows: list[Window]) -> PrototypeFacts:
    async def load(session_factory: Any, room_id: uuid.UUID) -> LoadedWindows:
        return LoadedWindows(windows=windows, render=lambda w: "[1] 대화", user_name="나")

    return PrototypeFacts(
        store=FactStore(tmp_path / "facts.jsonl"), caller=caller, instruction="i", version="v1", load=load
    )


def _one_fact() -> PrototypeFactResult:
    fact = PrototypeFact(
        kind="fact",
        subject="민지",
        object="",
        attribute="생일",
        value="5월",
        truth_status="confirmed",
        asserted_by="narration",
        speaker="",
        known_by=[],
        importance=3,
        start_line=1,
        end_line=2,
    )
    return PrototypeFactResult(facts=[fact])


def test_prototype_catch_up_reports_progress_one_window_per_turn(tmp_path: Path) -> None:
    windows = [_window(), _window()]

    async def caller(prompt: str) -> PrototypeFactResult:
        return _one_fact()

    proto = _prototype(tmp_path, caller, windows)
    first = asyncio.run(proto.run_once(_NO_DB, uuid.uuid4(), uuid.uuid4()))
    assert (first["pendingBefore"], first["doneBefore"], first["doneAfter"]) == (2, 0, 1)
    second = asyncio.run(proto.run_once(_NO_DB, uuid.uuid4(), uuid.uuid4()))
    assert (second["pendingBefore"], second["doneAfter"]) == (1, 2)
    idle = asyncio.run(proto.run_once(_NO_DB, uuid.uuid4(), uuid.uuid4()))
    assert (idle["pendingBefore"], idle["doneBefore"], idle["doneAfter"]) == (0, 2, 2)
    status = asyncio.run(proto.snapshot_status(cast(Any, None), windows[0].snapshot_id))
    assert status == "done"
    assert asyncio.run(proto.snapshot_status(cast(Any, None), uuid.uuid4())) is None


def test_prototype_call_failure_is_no_progress_and_the_budget_stop_still_raises(tmp_path: Path) -> None:
    async def broken(prompt: str) -> PrototypeFactResult:
        raise RuntimeError("파싱 실패")

    proto = _prototype(tmp_path, broken, [_window()])
    state = asyncio.run(proto.run_once(_NO_DB, uuid.uuid4(), uuid.uuid4()))
    assert state["doneAfter"] == state["doneBefore"] == 0
    assert "파싱 실패" in state["error"]

    async def over(prompt: str) -> PrototypeFactResult:
        raise BudgetExceededError("상한")

    with pytest.raises(BudgetExceededError):
        asyncio.run(_prototype(tmp_path, over, [_window()]).run_once(_NO_DB, uuid.uuid4(), uuid.uuid4()))
