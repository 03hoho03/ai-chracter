"""프로브를 작업자 여럿으로 나눠 돌릴 때 작업자끼리 서로의 자원을 깨지 않는지.

작업자마다 서버 포트·작업 DB·Redis 번호·쿠키 파일이 따로다. 모든 작업 DB 는 같은 템플릿의 사본이라 방 id 와 측정 계정 id 가
같다 — 같은 Redis 를 쓰면 방 턴 락과 사용자별 분당 버스트 카운터를 작업자 전원이 함께 쓴다. 그래서 서버 env 의 Redis 와 하네스
프로세스가 지우고 확인하는 Redis 가 같은 작업자 번호여야 한다.

원장은 여러 작업자(스레드·프로세스)가 함께 쓰므로 여유 확인과 기록이 한 잠금 안에서 일어나고, 확인을 통과한 호출은 끝날 때까지
견적만큼 자리를 잡아 둔다 — 상한 직전에서 동시에 확인한 작업자들이 함께 통과해 상한을 넘지 않게.

문항 id·방 id 는 이 테스트를 위해 지어낸 것이다."""

import asyncio
import fcntl
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from memory_eval.ledger import BudgetExceededError, Ledger, cost_usd
from memory_eval.plants import Probe
from memory_eval.probe import BurstPacer, ProbeRun

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
# 원장 한 줄 = 0.1 달러(Haiku 5.5 입력 100만 토큰).
ROW_USD = cost_usd(
    "claude-haiku-5-5",
    input_tokens=1_000_000,
    cached_tokens=0,
    cache_write_tokens=0,
    output_tokens=0,
    thoughts_tokens=0,
)
BASE_URL = "postgresql+asyncpg://x@localhost/lm_eval_work"


def _append(book: Ledger) -> None:
    book.append(
        stage="t",
        call_site="memory_eval_test",
        model="claude-haiku-5-5",
        input_tokens=1_000_000,
        cached_tokens=0,
        cache_write_tokens=0,
        output_tokens=0,
        thoughts_tokens=0,
    )


# ---------------------------------------------------------------- 작업자 자리


def test_worker_slots_never_share_a_port_work_database_redis_index_or_cookie_file(tmp_path: Path) -> None:
    from memory_eval.workers import MAX_WORKERS, worker_slots

    for count in range(1, MAX_WORKERS + 1):
        slots = worker_slots(
            count,
            base_port=8130,
            database_url=BASE_URL,
            redis_url="redis://localhost:6380/0",
            redis_db_base=8,
            cookie_file=tmp_path / "cookie",
        )
        assert [s.index for s in slots] == list(range(1, count + 1))
        for field in ("port", "database_url", "redis_url", "cookie_file"):
            values = [getattr(s, field) for s in slots]
            assert len(set(values)) == count, field
    slots = worker_slots(
        MAX_WORKERS,
        base_port=8130,
        database_url=BASE_URL,
        redis_url="redis://localhost:6380/0",
        redis_db_base=8,
        cookie_file=tmp_path / "cookie",
    )
    assert [s.port for s in slots] == list(range(8131, 8138))
    assert [s.redis_url for s in slots] == [f"redis://localhost:6380/{n}" for n in range(9, 16)]
    assert slots[0].database_url.endswith("/lm_eval_work_probe_w1")
    assert slots[0].cookie_file != tmp_path / "cookie"


def test_worker_slots_refuse_too_many_workers_an_unknown_redis_index_and_a_non_eval_database(tmp_path: Path) -> None:
    from memory_eval.workers import MAX_WORKERS, worker_slots

    common: dict[str, Any] = {"base_port": 8130, "redis_url": "redis://localhost:6380/0", "cookie_file": tmp_path / "c"}
    with pytest.raises(SystemExit):
        worker_slots(MAX_WORKERS + 1, database_url=BASE_URL, redis_db_base=8, **common)
    with pytest.raises(SystemExit):
        worker_slots(0, database_url=BASE_URL, redis_db_base=8, **common)
    # Redis 기본 설정의 DB 번호는 0~15 뿐이다.
    with pytest.raises(SystemExit):
        worker_slots(3, database_url=BASE_URL, redis_db_base=14, **common)
    with pytest.raises(SystemExit):
        worker_slots(1, database_url="postgresql+asyncpg://x@localhost/devdb", redis_db_base=8, **common)
    # Postgres 는 63바이트를 넘는 DB 이름의 뒤쪽을 버리므로 서로 다른 작업자의 DB 가 같은 이름이 될 수 있다 — 미리 거부한다.
    long_url = "postgresql+asyncpg://x@localhost/lm_eval_" + "x" * 50
    with pytest.raises(SystemExit):
        worker_slots(1, database_url=long_url, redis_db_base=8, **common)


def _fake_restore_world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """복원은 실제 함수로 돌리고 DB 복제·지문 읽기와 Redis 연결만 흉내 낸다 — 하네스가 어느 Redis URL 로 지우고 확인하는지 본다."""
    from redis.asyncio import Redis

    from memory_eval import checkpoint as checkpoint_mod
    from memory_eval import probe as probe_mod
    from memory_eval import server as server_mod

    seen: dict[str, Any] = {"redis": [], "server": [], "clone": []}
    fingerprint = {"turnCount": 50}
    checkpoint_mod.write_fingerprint(checkpoint_mod.fingerprint_path(tmp_path / "dumps", 50, "s4"), fingerprint)

    class FakeRedis:
        async def scan_iter(self, match: str) -> Any:
            keys: tuple[str, ...] = ()
            for key in keys:
                yield key

        async def delete(self, key: str) -> int:
            return 0

        async def exists(self, key: str) -> int:
            return 0

        async def aclose(self) -> None:
            return None

    def from_url(url: str, **_: Any) -> FakeRedis:
        seen["redis"].append(url)
        return FakeRedis()

    async def clone(database_url: str, **kwargs: Any) -> None:
        seen["clone"].append(kwargs)

    async def read_fp(*_: Any) -> dict[str, Any]:
        return dict(fingerprint)

    def start(overrides: dict[str, str], **kwargs: Any) -> Any:
        seen["server"].append({**overrides, "port": kwargs["port"]})
        kwargs["log"].write_text("")
        return server_mod.ServerHandle(process=None, base="http://fake", log=kwargs["log"])  # type: ignore[arg-type]

    def driver(run: Any, base: str, folder: Path, *extra: str) -> int:
        if extra[0] == "--say":
            with (folder / "chat.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"kind": "turn", "reply": "응답"}) + "\n")
        return 0

    async def empty(*_: Any) -> list[Any]:
        return []

    async def consent(*_: Any) -> None:
        return None

    monkeypatch.setattr(Redis, "from_url", staticmethod(from_url))
    monkeypatch.setattr(checkpoint_mod, "clone_database", clone)
    monkeypatch.setattr(checkpoint_mod, "read_fingerprint", read_fp)
    monkeypatch.setattr(server_mod, "start", start)
    monkeypatch.setattr(server_mod, "stop", lambda _h: None)
    monkeypatch.setattr(probe_mod, "_driver", driver)
    monkeypatch.setattr(probe_mod, "_turn_usage", empty)
    monkeypatch.setattr(probe_mod, "_turn_memory_facts", empty)
    monkeypatch.setattr(probe_mod, "_turn_memory_recall", empty)
    monkeypatch.setattr(probe_mod, "_ensure_consent", consent)
    return seen


def _run(tmp_path: Path, **kwargs: Any) -> ProbeRun:
    fields: dict[str, Any] = {
        "stage": "s4",
        "arm": "baseline",
        "room_id": uuid.uuid4(),
        "run_dir": tmp_path,
        "database_url": BASE_URL,
        "cred_file": tmp_path / "cred",
        "cookie_file": tmp_path / "cookie",
        "port": 8130,
        "server_overrides": {},
        "allow_paid": False,
        "opus_turn_usd": 0.13,
        "judgment_turn_usd": 0.003,
        "ledger": Ledger(tmp_path / "ledger.jsonl", cap_usd=30.0),
        "pacer": BurstPacer(limit=9, window_seconds=60.0),
        "checkpoint_label": "s4",
    }
    fields.update(kwargs)
    return ProbeRun(**fields)


def test_a_worker_clears_and_checks_the_same_redis_index_its_server_is_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """작업자 Redis 를 서버 env 에만 주면 하네스는 자기 설정의 Redis 에서 방 키·Voyage 멈춤 키를 지우고, 서버가 쓰는 Redis 의
    턴 락·멈춤 키는 그대로 남는다. 같은 템플릿 사본이라 방·사용자 id 가 같으니 분당 버스트 카운터도 작업자마다 갈라야 한다."""
    from memory_eval import probe as probe_mod
    from memory_eval.workers import worker_slots

    seen = _fake_restore_world(monkeypatch, tmp_path)
    slots = worker_slots(
        3,
        base_port=8130,
        database_url=BASE_URL,
        redis_url="redis://localhost:6380/0",
        redis_db_base=8,
        cookie_file=tmp_path / "cookie",
    )
    for slot in slots:
        seen["redis"].clear()
        run = _run(
            tmp_path,
            port=slot.port,
            database_url=slot.database_url,
            redis_url=slot.redis_url,
            cookie_file=slot.cookie_file,
        )
        result = probe_mod.run_probe(
            run, Probe(item_id=f"q{slot.index}", checkpoint=50, turns=["질문"], kind="plant", split="dev")
        )
        assert result["status"] == "accept"
        # 복원의 방 키 정리와 보내기 직전 멈춤 키 확인, 둘 다 작업자 Redis 다.
        assert seen["redis"] and set(seen["redis"]) == {slot.redis_url}
        server_env = seen["server"][-1]
        assert server_env["REDIS_URL"] == slot.redis_url
        assert server_env["DATABASE_URL"] == slot.database_url
        assert server_env["port"] == slot.port
    assert len({env["REDIS_URL"] for env in seen["server"]}) == 3


# ---------------------------------------------------------------- 템플릿 복제 잠금(실제 Postgres)


async def _admin(sql: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from api.core.config import settings
    from memory_eval.checkpoint import maintenance_url

    engine = create_async_engine(maintenance_url(settings.database_url), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


async def _exists(name: str) -> bool:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from api.core.config import settings
    from memory_eval.checkpoint import maintenance_url

    engine = create_async_engine(maintenance_url(settings.database_url), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            return bool(await conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}))
    finally:
        await engine.dispose()


@pytest.fixture
def template_db() -> Any:
    name = f"lm_eval_wtest{uuid.uuid4().hex[:8]}"
    asyncio.run(_admin(f'CREATE DATABASE "{name}_src" TEMPLATE template0'))
    try:
        yield name
    finally:
        for suffix in ("_src", "_w1", "_w2"):
            asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{name}{suffix}"'))


def test_two_workers_cloning_the_same_template_at_once_both_get_their_database(
    template_db: str, tmp_path: Path
) -> None:
    from api.core.config import settings
    from memory_eval.checkpoint import clone_database

    lock = tmp_path / "clone.lock"
    start = threading.Barrier(2)
    errors: list[BaseException] = []

    def clone(target: str) -> None:
        start.wait(timeout=10)
        try:
            for _ in range(2):  # 두 번째는 있던 작업 DB 를 지우고 다시 만드는 길
                asyncio.run(
                    clone_database(
                        settings.database_url, source=f"{template_db}_src", target=target, replace=True, lock=lock
                    )
                )
        except BaseException as exc:  # SystemExit 도 실패로 센다
            errors.append(exc)

    threads = [threading.Thread(target=clone, args=(f"{template_db}_w{i}",)) for i in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert errors == []
    assert asyncio.run(_exists(f"{template_db}_w1"))
    assert asyncio.run(_exists(f"{template_db}_w2"))


def test_cloning_waits_while_another_worker_holds_the_clone_lock(template_db: str, tmp_path: Path) -> None:
    from api.core.config import settings
    from memory_eval.checkpoint import clone_database

    lock = tmp_path / "clone.lock"
    target = f"{template_db}_w1"
    with lock.open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        worker = threading.Thread(
            target=lambda: asyncio.run(
                clone_database(
                    settings.database_url, source=f"{template_db}_src", target=target, replace=True, lock=lock
                )
            )
        )
        worker.start()
        worker.join(timeout=1.5)
        assert worker.is_alive()
        assert not asyncio.run(_exists(target))
        fcntl.flock(held, fcntl.LOCK_UN)
    worker.join(timeout=60)
    assert not worker.is_alive()
    assert asyncio.run(_exists(target))


# ---------------------------------------------------------------- 원장 잠금


_CHILD = """
import os, sys, time
from pathlib import Path
from memory_eval.ledger import BudgetExceededError, Ledger
path, mode, n, cap = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
book = Ledger(Path(path), cap_usd=cap)
def append():
    book.append(stage="t", call_site="memory_eval_test", model="claude-haiku-5-5", input_tokens=1_000_000,
                cached_tokens=0, cache_write_tokens=0, output_tokens=0, thoughts_tokens=0)
if mode == "append":
    for _ in range(n):
        append()
elif mode == "reserve":
    try:
        with book.reserve(0.1):
            time.sleep(1.0)
            append()
        print("ok")
    except BudgetExceededError:
        print("over")
elif mode == "die":
    with book.reserve(0.1):
        os._exit(0)
"""


def _child(path: Path, mode: str, n: int = 0, cap: float = 1e9) -> subprocess.Popen[str]:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(SCRIPTS_DIR), os.environ.get("PYTHONPATH", "")])}
    return subprocess.Popen(
        [sys.executable, "-c", _CHILD, str(path), mode, str(n), str(cap)],
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )


def test_appends_from_many_threads_and_processes_keep_every_row_and_a_running_total(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    book = Ledger(path)
    procs = [_child(path, "append", n=20) for _ in range(3)]

    def twenty() -> None:
        for _ in range(20):
            _append(book)

    threads = [threading.Thread(target=twenty) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for p in procs:
        assert p.wait(timeout=120) == 0
    rows = book.rows()
    assert len(rows) == 9 * 20
    assert book.total_usd() == pytest.approx(9 * 20 * ROW_USD)
    # 누적 칸은 기록 순서대로 한 줄씩 늘어난다 — 두 작업자가 같은 누적을 읽고 같은 값을 적지 않았다.
    cumulative = [r["cumulativeUsd"] for r in rows]
    assert cumulative == pytest.approx([ROW_USD * (i + 1) for i in range(len(rows))])


def test_workers_checking_at_once_just_below_the_cap_never_cross_it(tmp_path: Path) -> None:
    book = Ledger(tmp_path / "ledger.jsonl", cap_usd=1.05)
    for _ in range(7):
        _append(book)  # 0.7 달러 사용
    outcomes: list[str] = []
    start = threading.Barrier(10)

    def worker() -> None:
        start.wait(timeout=10)
        try:
            with book.reserve(0.1):
                time.sleep(0.3)
                _append(book)
            outcomes.append("ok")
        except BudgetExceededError:
            outcomes.append("over")

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["ok"] * 3 + ["over"] * 7
    assert book.total_usd() <= 1.05


def test_processes_reserving_at_once_never_cross_the_cap(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    book = Ledger(path, cap_usd=1.05)
    for _ in range(8):
        _append(book)  # 0.8 달러 사용 — 남은 자리는 두 호출
    procs = [_child(path, "reserve", cap=1.05) for _ in range(6)]
    outs = [p.communicate(timeout=120)[0].strip() for p in procs]
    assert all(o in ("ok", "over") for o in outs)
    assert "over" in outs
    assert book.total_usd() <= 1.05


def test_a_reservation_left_by_a_dead_process_does_not_hold_the_cap(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    book = Ledger(path, cap_usd=0.15)
    assert _child(path, "die").wait(timeout=120) == 0
    book.check_headroom(0.1)
    with book.reserve(0.1):
        with pytest.raises(BudgetExceededError):
            book.check_headroom(0.1)


async def test_parallel_judge_calls_near_the_cap_send_only_what_fits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """판정은 한 프로세스 안에서 동시에 나간다 — 확인과 응답 기록 사이에 다른 판정이 확인을 통과하면 상한을 넘는다."""
    import anthropic

    from memory_eval.judge import JUDGE_MODEL, JUDGE_MODELS, HaikuJudge, JudgeVerdict

    sent: list[int] = []
    release = asyncio.Event()

    class FakeMessages:
        async def create(self, **_: Any) -> SimpleNamespace:
            sent.append(1)
            await release.wait()
            usage = SimpleNamespace(
                input_tokens=10,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
                output_tokens=1,
                output_tokens_details=None,
            )
            body = JudgeVerdict(verdict="declined", reason="r").model_dump_json()
            return SimpleNamespace(
                stop_reason="end_turn", content=[SimpleNamespace(type="text", text=body)], usage=usage
            )

    class FakeClient:
        def __init__(self, **_: Any) -> None:
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeClient)
    estimate = JUDGE_MODELS[JUDGE_MODEL][1]
    judge = HaikuJudge("key", Ledger(tmp_path / "ledger.jsonl", cap_usd=estimate * 2.5), stage="judge")
    tasks = [asyncio.ensure_future(judge.verdict("p")) for _ in range(5)]
    await asyncio.sleep(0.05)
    release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert len(sent) == 2
    assert sum(isinstance(r, BudgetExceededError) for r in results) == 3


# ---------------------------------------------------------------- 병렬 실행


def test_one_failing_worker_does_not_stop_the_others_or_drop_their_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from memory_eval import probe as probe_mod
    from memory_eval.workers import run_parallel, worker_slots

    def run_probe(run: ProbeRun, probe: Probe) -> dict[str, Any]:
        time.sleep(0.05)
        if run.port == 8132:
            raise SystemExit("작업자 자원 오류")
        return {"checkpoint": probe.checkpoint, "item": probe.item_id, "status": "accept", "port": run.port}

    monkeypatch.setattr(probe_mod, "run_probe", run_probe)
    slots = worker_slots(
        3,
        base_port=8130,
        database_url=BASE_URL,
        redis_url="redis://localhost:6380/0",
        redis_db_base=8,
        cookie_file=tmp_path / "cookie",
    )
    out = tmp_path / "results.jsonl"
    progress: list[list[dict[str, Any]]] = []

    def on_result(row: dict[str, Any]) -> bool:
        with out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        return False

    probes = [Probe(item_id=f"q{i}", checkpoint=50, turns=["질문"], kind="plant", split="dev") for i in range(9)]
    outcome = run_parallel(_run(tmp_path), probes, slots, on_result=on_result, progress=progress.append)
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(outcome.failures) == 1
    failure = outcome.failures[0]
    assert failure["worker"] == 2 and "작업자 자원 오류" in failure["error"]
    # 실패한 단위만 빠지고 나머지 여덟은 다른 두 작업자가 끝냈다.
    assert sorted(r["item"] for r in rows) == sorted(p.item_id for p in probes if p.item_id != failure["item"])
    assert {r["port"] for r in rows} == {8131, 8133}
    assert outcome.budget_stop is None and outcome.remaining == 0
    states = {w["worker"]: w["state"] for w in progress[-1]}
    assert states == {1: "done", 2: "failed", 3: "done"}


def test_a_budget_stop_lets_running_units_finish_and_hands_out_no_new_ones(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from memory_eval import probe as probe_mod
    from memory_eval.workers import run_parallel, worker_slots

    calls: list[str] = []

    def run_probe(run: ProbeRun, probe: Probe) -> dict[str, Any]:
        calls.append(probe.item_id)
        if probe.item_id == "q0":
            time.sleep(0.05)  # 다른 작업자가 q1 을 받아 간 뒤에 멈춘다
            raise BudgetExceededError("상한")
        time.sleep(0.2)
        return {"checkpoint": probe.checkpoint, "item": probe.item_id, "status": "accept"}

    monkeypatch.setattr(probe_mod, "run_probe", run_probe)
    slots = worker_slots(
        2,
        base_port=8130,
        database_url=BASE_URL,
        redis_url="redis://localhost:6380/0",
        redis_db_base=8,
        cookie_file=tmp_path / "cookie",
    )
    rows: list[dict[str, Any]] = []
    probes = [Probe(item_id=f"q{i}", checkpoint=50, turns=["질문"], kind="plant", split="dev") for i in range(6)]

    def on_result(row: dict[str, Any]) -> bool:
        rows.append(row)
        return False

    outcome = run_parallel(_run(tmp_path), probes, slots, on_result=on_result)
    assert isinstance(outcome.budget_stop, BudgetExceededError)
    assert [r["item"] for r in rows] == ["q1"]
    assert outcome.failures == []
    # 결과 없이 끝난 단위(상한에 걸린 q0)도 내주지 않은 단위(q2~q5)와 함께 남은 단위로 센다 — 다음 실행이 다시 돈다.
    assert outcome.remaining == 5


# ---------------------------------------------------------------- 서버 충돌 검사


def test_own_worker_ports_in_this_tree_pass_and_every_other_server_on_the_shared_trees_is_refused() -> None:
    from memory_eval.server import conflicting_servers

    own = "/w/root/.claude/worktrees/long-memory-a/apps/api"
    trees = ["/w/root/.claude/worktrees/long-memory-a", "/w/root/.claude/worktrees/long-memory-b", "/w/root"]
    procs = [
        (1, own, 8131),
        (2, own, 8132),
        (3, own, 8140),  # 이 트리지만 작업자 포트가 아니다
        (4, "/w/root/.claude/worktrees/long-memory-b/apps/api", 8131),  # 다른 트리의 같은 포트
        (5, "/w/root/apps/api", None),
        (6, "/elsewhere/apps/api", 8000),
    ]
    found = conflicting_servers(procs, trees, own_pids=set(), own_ports={8131, 8132}, own_tree=own)
    assert [pid for pid, *_ in found] == [3, 4, 5]


def test_cleanup_picks_only_servers_of_this_tree_on_this_runs_worker_ports() -> None:
    """중단된 실행이 남긴 작업자 서버만 내린다 — 다른 트리의 측정 서버나 이 트리의 다른 포트(개발 서버 등)는 건드리지 않는다."""
    from memory_eval.server import leftover_worker_servers

    own = "/w/root/.claude/worktrees/long-memory-a/apps/api"
    procs = [
        (1, own, 8131),
        (2, own, 8137),
        (3, own, 8130),  # 기준 포트 자체는 작업자 포트가 아니다
        (4, own, 8138),  # 작업자 수 상한 밖
        (5, "/w/root/.claude/worktrees/long-memory-b/apps/api", 8132),  # 다른 트리의 작업자 포트
        (6, own, None),
        (7, "", 8133),  # 어느 트리인지 모른다
        (8, "/w/root/.claude/worktrees/long-memory-a/apps/api-old", 8134),  # 이름만 앞이 같은 다른 폴더
    ]
    assert leftover_worker_servers(procs, own_tree=own, ports=range(8131, 8138)) == [(1, 8131), (2, 8137)]


def test_probe_cleanup_command_stops_only_the_selected_servers_and_prints_pid_and_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval import server
    from memory_eval_cli import main

    own = str(server.API_DIR)
    procs = [(41, own, 8131), (42, own, 8000), (43, "/elsewhere/apps/api", 8132)]
    monkeypatch.setattr(server, "running_api_servers", lambda: procs)
    stopped: list[list[int]] = []

    def fake_stop(pids: list[int], **_: Any) -> list[int]:
        stopped.append(list(pids))
        return []

    monkeypatch.setattr(server, "stop_pids", fake_stop)
    assert main(["--run", str(tmp_path), "probe-cleanup", "--port", "8130"]) == 0
    assert stopped == [[41]]
    out = json.loads(capsys.readouterr().out)
    assert out["stopped"] == [{"pid": 41, "port": 8131}]


def test_stop_pids_terminates_politely_then_kills_what_ignores_the_terminate_signal() -> None:
    """SIGTERM 으로 끝나는 프로세스는 그것으로 끝나고, SIGTERM 을 무시하는 프로세스는 기다린 뒤 SIGKILL 로 내린다."""
    import signal

    from memory_eval.server import stop_pids

    polite = subprocess.Popen(["sleep", "60"])
    stubborn = subprocess.Popen(
        [sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); time.sleep(60)"],
        stdout=subprocess.PIPE,
        text=True,
    )  # fmt: skip
    try:
        assert stubborn.stdout is not None and stubborn.stdout.readline().strip() == "ready"
        # 이 테스트 프로세스의 자식이라 죽은 뒤 거두지 않으면 좀비로 남아 살아 있는 것처럼 보인다 — 운영에서 내리는 서버는 자식이 아니다.
        reapers = [threading.Thread(target=proc.wait, daemon=True) for proc in (polite, stubborn)]
        for reaper in reapers:
            reaper.start()
        killed = stop_pids([polite.pid, stubborn.pid], timeout=2.0)
        for reaper in reapers:
            reaper.join(timeout=10)
        assert killed == [stubborn.pid]
        assert polite.returncode == -signal.SIGTERM
        assert stubborn.returncode == -signal.SIGKILL
    finally:
        for proc in (polite, stubborn):
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_shared_trees_are_found_from_the_root_checkout_and_from_a_worktree(tmp_path: Path) -> None:
    from memory_eval.server import harness_trees

    root = tmp_path / "repo"
    (root / "apps/api").mkdir(parents=True)
    _git("init", "-q", cwd=root)
    _git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i", cwd=root)
    worktree = root / ".claude/worktrees/long-memory-x"
    sibling = root / ".claude/worktrees/long-memory-y"
    for tree in (worktree, sibling):
        _git("worktree", "add", "-q", "--detach", str(tree), cwd=root)
        (tree / "apps/api").mkdir(parents=True)
    (root / ".claude/worktrees/other").mkdir()
    trees = {str(worktree.resolve()), str(sibling.resolve())}
    # 루트에서 돌면 루트 자신과 측정 워크트리들, 워크트리에서 돌면 자기와 형제 측정 워크트리 — 워크트리에서 돌 때도 형제가
    # 보여야 저장소 루트를 제대로 찾은 것이다(자기 트리를 루트로 잡으면 형제가 빠진다).
    assert set(harness_trees(root / "apps/api")) == {str(root.resolve()), *trees}
    assert set(harness_trees(worktree / "apps/api")) == trees


def test_shared_trees_outside_a_git_checkout_are_refused_rather_than_silently_empty(tmp_path: Path) -> None:
    from memory_eval.server import harness_trees

    (tmp_path / "apps/api").mkdir(parents=True)
    with pytest.raises(SystemExit):
        harness_trees(tmp_path / "apps/api")


def test_an_interrupt_in_the_main_thread_hands_out_no_new_units_and_waits_for_running_ones(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ctrl-C 를 받으면 새 단위를 내주지 않고, 돌던 단위는 끝까지 돌려 결과를 남기고, 작업자가 모두 끝난 뒤에 인터럽트를 다시
    올린다 — 작업자가 남아 있으면 띄운 서버가 주인 없이 남는다."""
    import _thread

    from memory_eval import probe as probe_mod
    from memory_eval.workers import run_parallel, worker_slots

    calls: list[str] = []

    def run_probe(run: ProbeRun, probe: Probe) -> dict[str, Any]:
        calls.append(probe.item_id)
        if probe.item_id == "q0":
            time.sleep(0.05)  # 다른 작업자가 q1 을 받아 간 뒤에 인터럽트가 난다
            _thread.interrupt_main()
        time.sleep(0.4)
        return {"checkpoint": probe.checkpoint, "item": probe.item_id, "status": "accept"}

    monkeypatch.setattr(probe_mod, "run_probe", run_probe)
    slots = worker_slots(
        2,
        base_port=8130,
        database_url=BASE_URL,
        redis_url="redis://localhost:6380/0",
        redis_db_base=8,
        cookie_file=tmp_path / "cookie",
    )
    rows: list[dict[str, Any]] = []

    def on_result(row: dict[str, Any]) -> bool:
        rows.append(row)
        return False

    probes = [Probe(item_id=f"q{i}", checkpoint=50, turns=["질문"], kind="plant", split="dev") for i in range(6)]
    with pytest.raises(KeyboardInterrupt):
        run_parallel(_run(tmp_path), probes, slots, on_result=on_result)
    assert not [t for t in threading.enumerate() if t.name.startswith("probe-w") and t.is_alive()]
    assert sorted(calls) == ["q0", "q1"]
    assert sorted(r["item"] for r in rows) == ["q0", "q1"]


def test_an_interrupted_command_leaves_an_interrupted_status_and_marker_after_its_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import memory_eval_cli
    from memory_eval.cli_common import update_status

    status_dir = tmp_path / "status"

    def interrupted(args: Any) -> int:
        update_status(status_dir, {"workers": [{"worker": 1, "state": "stopped"}]})
        raise KeyboardInterrupt

    monkeypatch.setattr(memory_eval_cli, "_run", interrupted)
    code = memory_eval_cli.main(["--run", str(tmp_path), "--status-dir", str(status_dir), "ledger"])
    status = json.loads((status_dir / "status.json").read_text(encoding="utf-8"))
    assert code == memory_eval_cli.EXIT_INTERRUPTED == 130
    assert status["state"] == "interrupted" and status["exitCode"] == 130
    assert status["workers"] == [{"worker": 1, "state": "stopped"}]
    assert sorted(p.name for p in status_dir.glob("done.*")) == ["done.130"]


def test_default_worker_slots_use_redis_indexes_above_what_parallel_pytest_takes(tmp_path: Path) -> None:
    """이 기계의 `pytest -n auto` 는 8코어라 Redis 1~8 을 쓴다 — 기본 기준 번호로 만든 작업자 자리는 그 위(9~15)만 쓴다."""
    from memory_eval.workers import MAX_WORKERS, worker_slots

    slots = worker_slots(
        MAX_WORKERS,
        base_port=8130,
        database_url=BASE_URL,
        redis_url="redis://localhost:6380/0",
        cookie_file=tmp_path / "cookie",
    )
    assert [s.redis_url for s in slots] == [f"redis://localhost:6380/{n}" for n in range(9, 16)]


def test_the_driver_runs_in_its_own_session_so_a_terminal_interrupt_does_not_kill_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """터미널의 Ctrl-C 는 전경 프로세스 그룹 전체에 간다 — 드라이버가 같이 죽으면 그 시도가 그 밖의 오류로 세져 재시도·불능으로
    번진다. 중단은 하네스가 받아 새 시도를 내지 않는 쪽으로만 처리한다."""
    import subprocess as subprocess_mod

    from memory_eval import probe as probe_mod

    seen: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        seen.update(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess_mod, "run", fake_run)
    folder = tmp_path / "attempt1"
    folder.mkdir()
    assert probe_mod._driver(_run(tmp_path), "http://fake", folder, "--say", "질문") == 0
    assert seen.get("start_new_session") is True


def test_a_probe_does_not_start_another_attempt_once_interrupted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """시도가 실패해 재시도할 차례라도 중단 표지가 섰으면 복원·서버 기동 없이 빠진다 — 결과를 만들지 않아 결과 파일·불능 수에
    들지 않고, 다음 실행이 그 단위를 처음부터 다시 돈다."""
    from memory_eval import probe as probe_mod

    seen = _fake_restore_world(monkeypatch, tmp_path)
    stop = threading.Event()

    def failing_driver(run: Any, base: str, folder: Path, *extra: str) -> int:
        if extra[0] == "--say":
            stop.set()
            return 1  # 그 밖의 오류 — 재시도 대상
        return 0

    monkeypatch.setattr(probe_mod, "_driver", failing_driver)
    run = _run(tmp_path, interrupted=stop.is_set)
    with pytest.raises(probe_mod.ProbeInterruptedError):
        probe_mod.run_probe(run, Probe(item_id="q1", checkpoint=50, turns=["질문"], kind="plant", split="dev"))
    assert len(seen["clone"]) == 1
    assert len(seen["server"]) == 1


def test_an_interrupt_during_a_retrying_unit_gives_no_result_and_keeps_failures_on_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ctrl-C 뒤 재시도할 단위는 결과 없이 빠지고(결과 콜백이 불리지 않는다), 그 전에 실패한 단위는 실패 파일에 남는다."""
    import _thread

    from memory_eval import probe as probe_mod
    from memory_eval.workers import run_parallel, worker_slots

    seen = _fake_restore_world(monkeypatch, tmp_path)
    real_run_probe = probe_mod.run_probe

    def run_probe(run: ProbeRun, probe: Probe) -> dict[str, Any]:
        if run.port == 8132:
            raise SystemExit("작업자 자원 오류")
        return real_run_probe(run, probe)

    def interrupting_driver(run: Any, base: str, folder: Path, *extra: str) -> int:
        if extra[0] == "--say":
            time.sleep(0.1)  # 다른 작업자의 실패가 먼저 적힌다
            _thread.interrupt_main()
            time.sleep(0.3)  # 메인이 중단 표지를 세운 뒤에 시도가 끝난다
            return 1
        return 0

    monkeypatch.setattr(probe_mod, "run_probe", run_probe)
    monkeypatch.setattr(probe_mod, "_driver", interrupting_driver)
    slots = worker_slots(
        2,
        base_port=8130,
        database_url=BASE_URL,
        redis_url="redis://localhost:6380/0",
        redis_db_base=8,
        cookie_file=tmp_path / "cookie",
    )
    rows: list[dict[str, Any]] = []

    def on_result(row: dict[str, Any]) -> bool:
        rows.append(row)
        return False

    failures = tmp_path / "failures.jsonl"
    probes = [Probe(item_id=f"q{i}", checkpoint=50, turns=["질문"], kind="plant", split="dev") for i in range(4)]
    with pytest.raises(KeyboardInterrupt):
        run_parallel(_run(tmp_path), probes, slots, on_result=on_result, failures_file=failures)
    assert rows == []
    assert len(seen["server"]) == 1  # 재시도 서버는 뜨지 않았다
    written = [json.loads(line) for line in failures.read_text(encoding="utf-8").splitlines()]
    assert [(f["worker"], "작업자 자원 오류" in f["error"]) for f in written] == [(2, True)]


def test_a_unit_stopped_mid_retry_counts_as_remaining_like_one_never_handed_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """멈춘 뒤 재시도 전에 빠진 단위는 결과가 없다 — 내주지 않은 단위와 같이 남은 단위로 센다."""
    from memory_eval import probe as probe_mod
    from memory_eval.workers import run_parallel, worker_slots

    def run_probe(run: ProbeRun, probe: Probe) -> dict[str, Any]:
        if probe.item_id == "q0":
            time.sleep(0.1)  # 다른 작업자가 q1 을 받아 간 뒤에 끝난다
            return {"checkpoint": probe.checkpoint, "item": probe.item_id, "status": "unprobeable"}
        assert run.interrupted is not None
        while not run.interrupted():  # q1: 재시도할 차례에 멈춤 표지를 본다
            time.sleep(0.01)
        raise probe_mod.ProbeInterruptedError(probe.item_id)

    monkeypatch.setattr(probe_mod, "run_probe", run_probe)
    slots = worker_slots(
        2,
        base_port=8130,
        database_url=BASE_URL,
        redis_url="redis://localhost:6380/0",
        redis_db_base=8,
        cookie_file=tmp_path / "cookie",
    )
    rows: list[dict[str, Any]] = []

    def on_result(row: dict[str, Any]) -> bool:
        rows.append(row)
        return True  # 불능 멈춤

    probes = [Probe(item_id=f"q{i}", checkpoint=50, turns=["질문"], kind="plant", split="dev") for i in range(4)]
    outcome = run_parallel(_run(tmp_path), probes, slots, on_result=on_result)
    assert [r["item"] for r in rows] == ["q0"]
    assert outcome.remaining == 3  # q1(재시도 전에 멈춤) + q2·q3(내주지 않음)


def test_an_interrupt_while_starting_workers_waits_only_for_the_started_ones(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """작업자를 띄우는 도중 Ctrl-C 가 오면 띄우지 못한 작업자의 끝 표지는 영영 서지 않는다 — 그것을 기다리면 멈추지 않는다."""
    from memory_eval import probe as probe_mod
    from memory_eval.workers import run_parallel, worker_slots

    real_start = threading.Thread.start
    starts: list[str] = []

    def start(self: threading.Thread) -> None:
        if self.name.startswith("probe-w"):
            starts.append(self.name)
            if len(starts) == 2:
                raise KeyboardInterrupt
        real_start(self)

    def run_probe(run: ProbeRun, probe: Probe) -> dict[str, Any]:
        time.sleep(0.05)
        return {"checkpoint": probe.checkpoint, "item": probe.item_id, "status": "accept"}

    monkeypatch.setattr(threading.Thread, "start", start)
    monkeypatch.setattr(probe_mod, "run_probe", run_probe)
    slots = worker_slots(
        3,
        base_port=8130,
        database_url=BASE_URL,
        redis_url="redis://localhost:6380/0",
        redis_db_base=8,
        cookie_file=tmp_path / "cookie",
    )
    probes = [Probe(item_id=f"q{i}", checkpoint=50, turns=["질문"], kind="plant", split="dev") for i in range(6)]
    raised: list[BaseException] = []

    def call() -> None:
        try:
            run_parallel(_run(tmp_path), probes, slots, on_result=lambda _r: False)
        except BaseException as exc:
            raised.append(exc)

    caller = threading.Thread(target=call, daemon=True, name="caller")
    real_start(caller)
    caller.join(timeout=10)
    assert not caller.is_alive(), "띄우지 못한 작업자를 기다리며 멈추지 않았다"
    assert len(raised) == 1 and isinstance(raised[0], KeyboardInterrupt)


def _rerun_world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """실제 서버처럼 로그를 이어 쓰는 가짜 서버와, 실행 번호를 남기는 가짜 드라이버(사용량 줄·턴·덤프 줄)."""
    from memory_eval import probe as probe_mod
    from memory_eval import server as server_mod

    seen = _fake_restore_world(monkeypatch, tmp_path)
    seen["run"] = 0

    def start(overrides: dict[str, str], **kwargs: Any) -> Any:
        with kwargs["log"].open("a", encoding="utf-8"):
            pass
        seen["dump"] = Path(overrides["PROMPT_DUMP_PATH"])
        return server_mod.ServerHandle(process=None, base="http://fake", log=kwargs["log"])  # type: ignore[arg-type]

    def driver(run: Any, base: str, folder: Path, *extra: str) -> int:
        if extra[0] != "--say":
            return 0
        tag = f"run{seen['run']}"
        with (folder / "server.log").open("a", encoding="utf-8") as log:
            log.write(
                "anthropic_usage call_site=chat_generate model=claude-opus-5-5 prompt_tokens=1000 "
                "cached_content_tokens=0 cache_write_tokens=0 candidates_tokens=10 thoughts_tokens=0\n"
                f"{probe_mod.RECALL_WARNING} {tag}\n"
            )
        with (folder / "chat.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": "turn", "reply": tag}) + "\n")
        with seen["dump"].open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": "generation", "prompt": tag}) + "\n")
        return 0

    monkeypatch.setattr(server_mod, "start", start)
    monkeypatch.setattr(probe_mod, "_driver", driver)
    return seen


def test_rerunning_a_unit_starts_from_empty_attempt_folders_and_keeps_the_old_ones_aside(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """다시 도는 단위가 지난 실행의 시도 폴더에 이어 쓰면 서버 로그의 옛 사용량이 원장에 다시 적히고, 마지막 턴·덤프·경고 집계가
    옛 줄을 집는다. 지난 폴더는 지우지 않고 옆으로 옮겨 증거로 남긴다."""
    from memory_eval import probe as probe_mod

    seen = _rerun_world(monkeypatch, tmp_path)
    run = _run(tmp_path)
    probe = Probe(item_id="q1", checkpoint=50, turns=["질문"], kind="plant", split="dev")
    item_dir = probe_mod.probe_dir(run, probe, 1).parent
    seen["run"] = 1
    probe_mod.run_probe(run, probe)
    rows_after_first = len(run.ledger.rows())
    seen["run"] = 2
    second = probe_mod.run_probe(run, probe)

    folder = Path(second["attempts"][-1]["folder"])
    assert folder.parent == item_dir
    assert "run1" not in (folder / "server.log").read_text(encoding="utf-8")
    assert "run1" not in (folder / "chat.jsonl").read_text(encoding="utf-8")
    assert "run1" not in (folder / "prompt-dump.jsonl").read_text(encoding="utf-8")
    assert second["turns"][-1]["reply"] == "run2"
    # 원장에는 두 번째 실행의 사용량 한 줄만 더해졌다.
    assert len(run.ledger.rows()) - rows_after_first == 1
    kept = sorted(p.name for p in item_dir.parent.iterdir() if p.name.startswith("q1.prev-"))
    assert len(kept) == 1
    assert "run1" in (item_dir.parent / kept[0] / "attempt1" / "server.log").read_text(encoding="utf-8")
    # 경고 집계는 결과 행이 가리키는 폴더만 읽는다 — 옮긴 폴더의 경고는 세지 않는다.
    assert probe_mod.injection_warnings_by_arm([second])["baseline"]["recall"] == 1


def test_a_second_rerun_in_the_same_second_keeps_both_old_folders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from memory_eval import probe as probe_mod

    seen = _rerun_world(monkeypatch, tmp_path)
    run = _run(tmp_path)
    probe = Probe(item_id="q1", checkpoint=50, turns=["질문"], kind="plant", split="dev")
    for n in (1, 2, 3):
        seen["run"] = n
        probe_mod.run_probe(run, probe)
    item_dir = probe_mod.probe_dir(run, probe, 1).parent
    assert len([p for p in item_dir.parent.iterdir() if p.name.startswith("q1.prev-")]) == 2


def test_an_interrupt_right_after_a_worker_started_still_waits_for_that_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`Thread.start` 는 스레드를 띄운 뒤 그 스레드가 돌기 시작했다는 표지를 기다린다 — 그 사이 Ctrl-C 가 와도 스레드는 이미 돈다.
    그 작업자도 끝날 때까지 기다려야 돌던 단위의 결과가 남고 서버가 주인 없이 남지 않는다."""
    from memory_eval import probe as probe_mod
    from memory_eval.workers import run_parallel, worker_slots

    real_start = threading.Thread.start
    starts: list[str] = []

    def start(self: threading.Thread) -> None:
        real_start(self)
        if self.name.startswith("probe-w"):
            starts.append(self.name)
            if len(starts) == 2:
                raise KeyboardInterrupt

    def run_probe(run: ProbeRun, probe: Probe) -> dict[str, Any]:
        time.sleep(0.3)
        return {"checkpoint": probe.checkpoint, "item": probe.item_id, "status": "accept"}

    monkeypatch.setattr(threading.Thread, "start", start)
    monkeypatch.setattr(probe_mod, "run_probe", run_probe)
    slots = worker_slots(
        2,
        base_port=8130,
        database_url=BASE_URL,
        redis_url="redis://localhost:6380/0",
        redis_db_base=8,
        cookie_file=tmp_path / "cookie",
    )
    rows: list[dict[str, Any]] = []

    def on_result(row: dict[str, Any]) -> bool:
        rows.append(row)
        return False

    probes = [Probe(item_id=f"q{i}", checkpoint=50, turns=["질문"], kind="plant", split="dev") for i in range(6)]
    with pytest.raises(KeyboardInterrupt):
        run_parallel(_run(tmp_path), probes, slots, on_result=on_result)
    assert not [t for t in threading.enumerate() if t.name.startswith("probe-w") and t.is_alive()]
    assert sorted(r["item"] for r in rows) == ["q0", "q1"]


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param(["--checkpoints", "50,100,50"], id="checkpoints"),
        pytest.param(["--checkpoints", "50", "--items", "q1,q2,q1"], id="items"),
    ],
)
def test_probe_refuses_a_repeated_checkpoint_or_item_before_planning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str]
) -> None:
    """같은 프로브가 큐에 두 번 들면 두 작업자가 같은 시도 폴더를 쓰고, 한쪽이 다시 돌 때 옮기는 지난 폴더가 다른 쪽이 쓰는 폴더다."""
    from memory_eval_cli import main

    argv = ["--run", str(tmp_path), "probe", "--plants", str(tmp_path / "없는-표.json"), "--stage", "s4"]
    assert main([*argv, "--arm", "A", *extra, "--dry-run"]) == 2
    assert "중복" in capsys.readouterr().err
