"""되감기 삭제 전 추출 확인 — 추출을 켠 실행은 그 메시지를 덮는 스냅샷의 추출이 끝나고(done) 그 턴을 덮는 에피소드가
있어야 지운다. 아니면 추출을 따라잡게 다시 부르고, 횟수 안에 안 되면 멈춘다. 추출을 끈 실행은 기록만 한다."""

import asyncio

import pytest

from memory_eval.insert import RewindState, delete_succeeded, ensure_rewind_ready, rewind_ready


def _state(status: str | None, episodes: int | None) -> RewindState:
    return RewindState(snapshot_id="s1", extraction_status=status, covering_episodes=episodes)


@pytest.mark.parametrize(
    ("status", "episodes", "ready"),
    [("done", 1, True), ("done", 0, False), ("failed", 2, False), ("running", 1, False), (None, None, False)],
)
def test_extract_run_needs_done_extraction_and_a_covering_episode(
    status: str | None, episodes: int | None, ready: bool
) -> None:
    assert rewind_ready(_state(status, episodes), extract=True) is ready


def test_run_without_extraction_never_waits() -> None:
    assert rewind_ready(_state(None, None), extract=False)


def test_not_ready_state_is_caught_up_by_extraction_then_deleted() -> None:
    states = iter([_state("running", 0), _state("done", 0), _state("done", 2)])
    calls: list[str] = []

    async def read() -> RewindState:
        return next(states)

    async def extract() -> None:
        calls.append("extract")

    final = asyncio.run(ensure_rewind_ready(read, extract, extract_enabled=True, attempts=3))
    assert final == _state("done", 2)
    assert calls == ["extract", "extract"]


def test_extraction_that_never_catches_up_stops_the_insert() -> None:
    calls: list[str] = []

    async def read() -> RewindState:
        return _state("failed", 0)

    async def extract() -> None:
        calls.append("extract")

    with pytest.raises(SystemExit, match="되감기"):
        asyncio.run(ensure_rewind_ready(read, extract, extract_enabled=True, attempts=3))
    assert len(calls) == 3


def test_run_without_extraction_records_the_state_without_extracting() -> None:
    calls: list[str] = []

    async def read() -> RewindState:
        return _state(None, None)

    async def extract() -> None:
        calls.append("extract")

    assert asyncio.run(ensure_rewind_ready(read, extract, extract_enabled=False, attempts=3)) == _state(None, None)
    assert calls == []


@pytest.mark.parametrize(("status", "ok"), [(200, True), (204, True), (404, False), (409, False), (500, False)])
def test_message_delete_counts_as_done_on_200_with_a_body_and_on_204_from_older_servers(status: int, ok: bool) -> None:
    """지금 서버는 메시지 삭제에 200 과 스탯 되감기 결과를 돌려주고, 그 전 서버는 본문 없는 204 를 돌려준다. 둘 다 지운 것이므로
    투입이 되감기 도중 멈추면 안 된다."""
    assert delete_succeeded(status) is ok
