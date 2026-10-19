"""프로브를 작업자 여럿으로 나눠 돌린다 — 작업자 자리(서버 포트·작업 DB·Redis 번호·쿠키 파일) 배정과 병렬 실행.

작업 단위는 프로브 하나(체크포인트 × 문항)다. 한 번의 프로브 명령은 갈래 하나·심기 표 하나를 돌리므로, 그 안에서 나눌 수 있는
가장 작은 독립 단위가 프로브다(재시도도 프로브 단위로 복원부터 다시 한다). 작업자는 한 큐에서 단위를 하나씩 받아 간다.

작업자 i(1부터)는 서버 포트 = 기본 포트 + i, 작업 DB = `<작업 DB>_probe_w<i>`, Redis DB 번호 = 기준 번호 + i, 쿠키 파일 =
`<쿠키 파일>.w<i>` 를 쓴다. 모든 작업 DB 가 같은 템플릿의 사본이라 방 id 와 측정 계정 id 가 작업자마다 같다 — 같은 Redis 를
쓰면 방 턴 락이 작업자끼리 부딪히고, 사용자별 분당 버스트 상한(사용자 id 로 키를 잡는 Redis 카운터)을 작업자 전원이 한
카운터로 나눠 쓰게 되어 작업자를 늘릴수록 429 에 걸린다. 작업자마다 Redis 번호를 따로 주면 둘 다 풀리고, 버스트 간격도
작업자마다 따로 센다. 세션도 Redis 에 있으므로 쿠키 파일도 작업자마다 따로다(드라이버가 401 이면 다시 로그인해 그 파일에 쓴다).

한 작업자의 단위가 실패하면(복원 거부·서버 기동 실패 등) 그 단위를 실패로 적고 그 작업자는 더 받지 않는다 — 작업자 자원이
깨졌을 수 있다. 다른 작업자는 계속 받아 간다. 원장 상한 멈춤이나 불능 멈춤이면 새 단위를 내주지 않고, 돌던 단위는 끝까지
돌려 결과를 남긴다."""

import dataclasses
import json
import threading
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.engine import make_url

from memory_eval import probe as probe_mod
from memory_eval.checkpoint import database_name, ensure_eval_db_name
from memory_eval.ledger import BudgetExceededError
from memory_eval.plants import Probe

DEFAULT_WORKERS = 3
# 작업자 하나가 서버(유휴 때 약 250MB 를 잰 적이 있고 턴 중엔 더 쓴다)·드라이버·작업 DB 를 더 쓴다 — 기계 메모리를 넘기지
# 않게 묶어 둔다. 기본 기준 번호에서 남는 Redis 번호 9~15 의 수이기도 하다.
MAX_WORKERS = 7
# 작업자 i 의 Redis DB 번호 = 기준 + i. 기본 8 이면 9~15 — pytest 병렬 실행(`-n`)은 작업자 gw<k> 마다 기본 번호 1 + k 를 쓰고
# `-n auto` 는 코어 수만큼 작업자를 띄우므로, 8코어 기계에서 1~8 을 쓴다. 코어가 8개를 넘는 기계에서 `-n auto` 를 함께 돌리면
# 겹치므로 기준 번호(`--redis-db-base`)를 올리거나 작업자를 줄인다.
DEFAULT_REDIS_DB_BASE = 8
# Redis 기본 설정의 DB 수(0~15).
REDIS_DATABASES = 16
# Postgres 는 이 바이트 수를 넘는 DB 이름의 뒤쪽을 버리고 받는다 — 길면 서로 다른 작업자의 DB 가 같은 이름이 될 수 있다.
PG_NAME_MAX_BYTES = 63


@dataclass(frozen=True)
class WorkerSlot:
    index: int
    port: int
    database_url: str
    redis_url: str
    cookie_file: Path


def worker_db_name(work_db: str, index: int) -> str:
    name = f"{work_db}_probe_w{index}"
    ensure_eval_db_name(name)
    if len(name.encode()) > PG_NAME_MAX_BYTES:
        raise SystemExit(f"작업자 작업 DB 이름이 {PG_NAME_MAX_BYTES}바이트를 넘는다(Postgres 가 잘라 받는다): {name}")
    return name


def worker_redis_url(redis_url: str, db: int) -> str:
    """같은 Redis 서버의 다른 DB 번호(URL 경로의 번호만 바꾼다)."""
    if not 0 <= db < REDIS_DATABASES:
        raise SystemExit(f"Redis DB 번호는 0~{REDIS_DATABASES - 1} 이다: {db}")
    parts = urlsplit(redis_url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{db}", parts.query, parts.fragment))


def worker_slots(
    count: int,
    *,
    base_port: int,
    database_url: str,
    redis_url: str,
    cookie_file: Path,
    redis_db_base: int = DEFAULT_REDIS_DB_BASE,
) -> list[WorkerSlot]:
    if not 1 <= count <= MAX_WORKERS:
        raise SystemExit(f"작업자 수는 1~{MAX_WORKERS} 이다: {count}")
    work_db = database_name(database_url)
    ensure_eval_db_name(work_db)
    url = make_url(database_url)
    return [
        WorkerSlot(
            index=i,
            port=base_port + i,
            database_url=url.set(database=worker_db_name(work_db, i)).render_as_string(hide_password=False),
            redis_url=worker_redis_url(redis_url, redis_db_base + i),
            cookie_file=cookie_file.with_name(f"{cookie_file.name}.w{i}"),
        )
        for i in range(1, count + 1)
    ]


@dataclass
class ParallelOutcome:
    # 실패한 단위(작업자·체크포인트·문항·오류). 결과 파일에는 들지 않아 다음 실행이 다시 돈다.
    failures: list[dict[str, Any]] = field(default_factory=list)
    budget_stop: BudgetExceededError | None = None
    # 결과 없이 끝난 단위 수 — 멈춤으로 내주지 않은 단위와, 멈춤·원장 상한으로 결과 전에 빠진 단위(실패 단위는 `failures`).
    remaining: int = 0


def run_parallel(
    run: "probe_mod.ProbeRun",
    probes: Sequence[Probe],
    slots: Sequence[WorkerSlot],
    *,
    on_result: Callable[[dict[str, Any]], bool],
    progress: Callable[[list[dict[str, Any]]], None] | None = None,
    failures_file: Path | None = None,
) -> ParallelOutcome:
    """`probes` 를 작업자(`slots`)마다 스레드 하나로 나눠 돌린다. 결과는 끝나는 대로 `on_result` 로 넘기고(한 번에 하나씩 —
    결과 파일 쓰기를 호출부가 따로 잠그지 않아도 된다), 그것이 참을 돌려주면 새 단위를 내주지 않는다. `progress` 는 작업자 상태가
    바뀔 때마다 상태 목록을 받는다.

    작업자는 `run` 을 자기 자리로 바꾼 사본으로 돈다. 버스트 간격은 작업자 Redis 의 카운터를 따르므로 작업자마다 새로 센다.

    멈출 때(Ctrl-C·원장 상한·불능 멈춤·`on_result` 의 참)는 새 단위를 내주지 않고, 돌던 시도는 끝까지 돌리되(서버를 내리고
    사용량을 원장에 남긴다) 그 단위의 다음 재시도는 시작하지 않는다 — 그 단위는 결과 없이 큐로 돌아가 다음 실행이 다시 돈다.
    실패한 단위는 생기는 대로 `failures_file` 에 한 줄씩 적는다 — Ctrl-C 로 예외가 올라가도 남게."""
    queue = deque(probes)
    lock = threading.Lock()
    outcome = ParallelOutcome()
    stopping = threading.Event()
    states: dict[int, dict[str, Any]] = {
        slot.index: {
            "worker": slot.index,
            "port": slot.port,
            "database": database_name(slot.database_url),
            "redisUrl": slot.redis_url,
            "state": "idle",
            "current": None,
            "done": 0,
            "failed": 0,
        }
        for slot in slots
    }

    def report() -> None:
        if progress is not None:
            progress([dict(states[i]) for i in sorted(states)])

    finished = {slot.index: threading.Event() for slot in slots}

    def work(slot: WorkerSlot) -> None:
        try:
            serve(slot)
        finally:
            finished[slot.index].set()

    def serve(slot: WorkerSlot) -> None:
        worker_run = dataclasses.replace(
            run,
            port=slot.port,
            database_url=slot.database_url,
            redis_url=slot.redis_url,
            cookie_file=slot.cookie_file,
            pacer=probe_mod.BurstPacer(limit=run.pacer.limit, window_seconds=run.pacer.window_seconds),
            interrupted=stopping.is_set,
        )
        state = states[slot.index]
        while True:
            with lock:
                if stopping.is_set() or not queue:
                    state.update(state="stopped" if stopping.is_set() and queue else "done", current=None)
                    report()
                    return
                probe = queue.popleft()
                state.update(state="running", current=f"cp{probe.checkpoint}/{probe.item_id}")
                report()
            try:
                result = probe_mod.run_probe(worker_run, probe)
            except probe_mod.ProbeInterruptedError:
                with lock:
                    queue.appendleft(probe)
                    state.update(state="stopped", current=None)
                    report()
                return
            except BudgetExceededError as exc:
                with lock:
                    # 결과 없이 끝난 단위는 멈춘 단위처럼 큐로 돌려 남은 단위로 센다(다음 실행이 다시 돈다).
                    queue.appendleft(probe)
                    stopping.set()
                    outcome.budget_stop = outcome.budget_stop or exc
                    state.update(state="stopped", current=None)
                    report()
                return
            except (Exception, SystemExit) as exc:
                failure = {
                    "worker": slot.index,
                    "checkpoint": probe.checkpoint,
                    "item": probe.item_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                with lock:
                    outcome.failures.append(failure)
                    if failures_file is not None:
                        failures_file.parent.mkdir(parents=True, exist_ok=True)
                        with failures_file.open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(failure, ensure_ascii=False) + "\n")
                    state.update(state="failed", current=None, failed=int(state["failed"]) + 1)
                    report()
                return
            with lock:
                state.update(done=int(state["done"]) + 1)
                if on_result(result):
                    stopping.set()
                report()

    threads = [threading.Thread(target=work, args=(slot,), name=f"probe-w{slot.index}") for slot in slots]
    # 기다릴 작업자 — 띄우는 도중 Ctrl-C 가 오면 띄우지 못한 작업자의 끝 표지는 영영 서지 않는다. `start` 는 스레드를 띄운 뒤
    # 그 스레드가 돌기 시작했다는 표지를 기다리므로, 그 사이에 Ctrl-C 가 와도 스레드는 이미 돈다 — 목록에 먼저 넣고, start 가
    # 예외로 끝났을 때 실제로 뜨지 못한 것(`ident` 없음)만 뺀다.
    started: list[tuple[threading.Event, threading.Thread]] = []
    try:
        for slot, thread in zip(slots, threads, strict=True):
            started.append((finished[slot.index], thread))
            try:
                thread.start()
            except BaseException:
                if thread.ident is None:
                    started.pop()
                raise
        _wait([event for event, _ in started], [thread for _, thread in started])
    except KeyboardInterrupt:
        # Ctrl-C: 멈춤 표지를 세우고(위 docstring 의 멈출 때) 작업자가 모두 끝난 뒤 다시 올린다. 기다리는 동안 다시 누른 Ctrl-C 는
        # 무시한다 — 작업자를 버리고 나가면 띄운 서버가 주인 없이 남는다.
        stopping.set()
        print("중단 요청 — 돌던 프로브가 끝나기를 기다린다", flush=True)
        while True:
            try:
                _wait([event for event, _ in started], [thread for _, thread in started])
                break
            except KeyboardInterrupt:
                continue
        raise
    outcome.remaining = len(queue)
    return outcome


def _wait(done: Iterable[threading.Event], threads: Sequence[threading.Thread]) -> None:
    """작업자마다 끝 표지를 짧게 끊어 기다린 뒤 스레드를 거둔다 — 메인 스레드가 인터럽트를 제때 받게. 표지가 서기 전에는
    `Thread.join` 으로 기다리지 않는다: join 이 인터럽트로 끊기면 아직 도는 스레드가 끝난 것으로 표시될 수 있어(`is_alive()` 가
    거짓 — 이 기계의 파이썬에서 재현했다), 돌던 단위의 결과가 남기 전에 빠져나간다. 표지가 선 뒤의 join 은 곧 끝난다."""
    for event in done:
        while not event.wait(timeout=0.1):
            pass
    # 표지를 세운 뒤 스레드는 곧 끝난다 — 끝까지 거둔다.
    for thread in threads:
        thread.join()
