"""SSE 제너레이터 라우트에서 `BackgroundTasks`가 언제 실행되고 언제 유실되는지 고정한다.

채팅 턴 뒤 후처리(예: 긴 대화 요약)를 제너레이터 본문 안, 턴 커밋 직후에 예약하려면 세 가지를
알아야 한다. ① 정상 종료 시 실행되는가 ② 클라이언트가 `done` 전에 끊으면 어떻게 되는가
③ `done` 뒤에 끊으면 어떻게 되는가. 이 저장소의 기존 `BackgroundTasks` 사용처는 전부 일반 JSON
라우트라 이 답을 주지 못한다.

하네스(`sse_harness.py`)가 실제 uvicorn 서버와 실제 소켓을 쓰는 이유는 그 모듈 docstring 에 있다.

결론(이 테스트들이 지키는 것):
- 정상 종료: 제너레이터가 끝까지 돈 뒤 background가 실행된다. `done` 뒤에 예약한 것도 실행된다.
- 끊김(시점 무관): 끊김이 처리되기 **전에** 예약된 것만 실행되고, 그다음 제너레이터가 취소된다.
  그래서 후처리는 `done`을 내보내기 **전에** 예약해야 한다 — `done` 뒤 코드는 끊김 한 번에
  예약 자체가 사라진다.
- uvicorn을 올려 서버가 `spec_version` 2.4 이상을 알리기 시작하면 끊김 시 background가 돌지 않아
  끊김 테스트 둘이 빨개진다 — 그때 이 결론을 다시 본다.
"""

import asyncio
from collections.abc import AsyncIterator, Callable

from fastapi import BackgroundTasks, FastAPI
from fastapi.sse import EventSourceResponse

from sse_harness import Recorder, run_probe


def _build_app(recorder: Recorder, body: Callable[[BackgroundTasks], AsyncIterator[dict[str, str]]]) -> FastAPI:
    app = FastAPI()

    @app.post("/probe", response_class=EventSourceResponse)
    async def probe(background_tasks: BackgroundTasks) -> AsyncIterator[dict[str, str]]:
        try:
            async for event in body(background_tasks):
                yield event
            recorder.events.append("gen:end")
        except asyncio.CancelledError:
            recorder.events.append("gen:cancelled")
            raise

    return app


async def test_background_runs_after_the_generator_finishes_on_normal_completion() -> None:
    recorder = Recorder()

    async def body(background_tasks: BackgroundTasks) -> AsyncIterator[dict[str, str]]:
        yield {"type": "token"}
        # 첫 yield 뒤(응답이 이미 시작된 뒤) 제너레이터 본문 안에서 예약해도 된다.
        background_tasks.add_task(recorder.task("before-done"))
        yield {"type": "done"}
        background_tasks.add_task(recorder.task("after-done"))

    received = await run_probe(_build_app(recorder, body), recorder, disconnect_on=None)

    assert [line for line in received if "done" in line] != []
    assert recorder.events == ["gen:end", "task:before-done", "task:after-done"]


async def test_disconnect_before_done_runs_only_tasks_scheduled_before_it() -> None:
    """턴 커밋 뒤 예약까지 마쳤는데 `done`이 가기 전에 클라이언트가 떠난 경우와, 예약 지점에
    닿기 전에 떠난 경우. 앞의 것은 실행되고 뒤의 것은 예약 자체가 일어나지 않는다."""
    recorder = Recorder()
    never = asyncio.Event()

    async def body(background_tasks: BackgroundTasks) -> AsyncIterator[dict[str, str]]:
        background_tasks.add_task(recorder.task("scheduled"))
        yield {"type": "token"}
        # 끊긴 뒤에도 제너레이터가 알아서 여기를 지나가지 않는다는 것을 보이려고 영영 기다린다.
        await never.wait()
        background_tasks.add_task(recorder.task("never-scheduled"))
        yield {"type": "done"}

    received = await run_probe(_build_app(recorder, body), recorder, disconnect_on="token")

    assert all("done" not in line for line in received)
    # background는 제너레이터가 취소되기 **전에** 돈다(요청 정리가 background 뒤에 온다).
    assert recorder.events == ["task:scheduled", "gen:cancelled"]


async def test_disconnect_after_done_runs_tasks_scheduled_before_done_and_drops_later_ones() -> None:
    recorder = Recorder()
    never = asyncio.Event()

    async def body(background_tasks: BackgroundTasks) -> AsyncIterator[dict[str, str]]:
        yield {"type": "token"}
        background_tasks.add_task(recorder.task("before-done"))
        yield {"type": "done"}
        # `done` 뒤 코드는 클라이언트가 떠나면 실행 기회를 잃는다.
        await never.wait()
        background_tasks.add_task(recorder.task("after-done"))

    received = await run_probe(_build_app(recorder, body), recorder, disconnect_on="done")

    assert [line for line in received if "done" in line] != []
    assert recorder.events == ["task:before-done", "gen:cancelled"]
