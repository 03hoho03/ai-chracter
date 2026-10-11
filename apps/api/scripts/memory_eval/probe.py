"""체크포인트 회상 프로브 — 계획, 실패 처리 판정, 분당 버스트 간격, 실제 실행 절차.

프로브 하나(대명사 문항은 맥락 턴 + 질문 턴 두 턴)를 보낼 때마다:
서버 정지 → 작업 DB 를 체크포인트 템플릿에서 다시 만들기 → 방 Redis 키 지우기 → 갈래 env 로 서버 기동(덤프 파일은 프로브마다
따로) → 지문 단언(복원 직후, 첫 턴 전) → 드라이버로 누적 기준을 다시 잡고(`--rebase`) 턴 전송 → 응답·덤프·사용량 저장.
메시지 삭제로 프로브를 지우지 않는다 — 삭제는 스탯·엔딩·턴 수를 되돌리지 않아 다음 프로브가 앞 프로브의 판정 결과를 물려받는다.

실패 처리(결과 전 고정, 갈래를 모른 채 같은 코드가 판정한다):
- 재시도 단위는 프로브 하나 전체이고, 재시도는 언제나 복원부터 다시 한다.
- 드라이버 종료 코드 4(분당 버스트): 60초 기다려 재시도, 최대 3회. 7(클로버 부족): 채운 뒤 재시도, 최대 3회.
- 3(엔딩 도달): 응답이 저장됐으면 그대로 채점(재시도 안 함), 저장되지 않았으면 재시도 최대 2회.
- 그 밖의 오류: 재시도 최대 2회. 단 서버 로그 스택이 회상 코드 안이면 재시도하지 않고 그 갈래의 오답으로 센다.
- 재시도를 다 쓰면 "프로브 불능". 불능이 전체 프로브의 5%를 넘으면 실행을 멈춘다."""

import asyncio
import json
import os
import subprocess
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memory_eval.ledger import Ledger
from memory_eval.plants import Probe
from memory_eval.server import API_DIR

EXIT_OK = 0
EXIT_ENDING = 3
EXIT_BURST = 4
EXIT_CLOVER = 7

BURST_WAIT_SECONDS = 60
_MAX_RETRIES = {"burst": 3, "clover": 3, "ending_unsaved": 2, "other": 2}


@dataclass(frozen=True)
class Attempt:
    """프로브 한 번 시도의 결과. `response_saved` 는 마지막 턴의 응답이 저장됐는가, `recall_stack` 은 서버 로그의 스택이
    회상(검색·주입) 코드 안에서 났는가다."""

    exit_code: int
    response_saved: bool = True
    recall_stack: bool = False


@dataclass(frozen=True)
class Action:
    kind: str  # accept · retry · unprobeable · count_wrong
    wait_seconds: int = 0
    top_up: bool = False
    reason: str = ""


def _reason(attempt: Attempt) -> str:
    if attempt.exit_code == EXIT_BURST:
        return "burst"
    if attempt.exit_code == EXIT_CLOVER:
        return "clover"
    if attempt.exit_code == EXIT_ENDING:
        return "ending_saved" if attempt.response_saved else "ending_unsaved"
    return "other"


def next_action(attempts: Sequence[Attempt]) -> Action:
    """지금까지의 시도(마지막이 방금 것)로 다음에 할 일을 정한다. 재시도 몫은 사유마다 따로 센다."""
    last = attempts[-1]
    if last.exit_code == EXIT_OK:
        return Action(kind="accept")
    reason = _reason(last)
    if reason == "ending_saved":
        return Action(kind="accept", reason="엔딩 도달 — 응답 저장됨")
    if reason == "other" and last.recall_stack:
        return Action(kind="count_wrong", reason="회상 코드 안의 오류")
    failures = sum(1 for a in attempts if _reason(a) == reason)
    if failures > _MAX_RETRIES[reason]:
        return Action(kind="unprobeable", reason=f"{reason} 재시도 {_MAX_RETRIES[reason]}회 소진")
    if reason == "burst":
        return Action(kind="retry", wait_seconds=BURST_WAIT_SECONDS, reason="분당 버스트")
    if reason == "clover":
        return Action(kind="retry", top_up=True, reason="클로버 부족")
    return Action(kind="retry", reason=f"종료 코드 {last.exit_code}")


def should_halt(unprobeable: int, total: int) -> bool:
    """불능이 전체 프로브의 5%(56문항이면 3)를 넘으면 멈춘다."""
    if total == 0:
        return False
    return unprobeable > round(0.05 * total)


@dataclass
class BurstPacer:
    """분당 버스트 상한은 Redis 카운터라 DB 복원으로 돌아가지 않는다. 드라이버의 간격 스탬프는 프로브 폴더마다 새로 생겨
    초기화되므로 하네스가 보낸 시각을 따로 세어 창 안 전송 수를 상한 아래로 둔다."""

    limit: int
    window_seconds: float
    sent: list[float] = field(default_factory=list)

    def record(self, at: float) -> None:
        self.sent.append(at)

    def wait_before_send(self, *, now: float) -> float:
        recent = sorted(t for t in self.sent if now - t < self.window_seconds)
        if len(recent) < self.limit:
            return 0.0
        oldest_blocking = recent[len(recent) - self.limit]
        return max(0.0, oldest_blocking + self.window_seconds - now)


# ---------------------------------------------------------------- 실행


@dataclass
class ProbeRun:
    """한 단계·한 갈래의 프로브 실행 설정."""

    stage: str
    arm: str
    room_id: uuid.UUID
    run_dir: Path
    database_url: str
    cred_file: Path
    cookie_file: Path
    port: int
    server_overrides: dict[str, str]
    allow_paid: bool
    opus_turn_usd: float
    judgment_turn_usd: float
    ledger: Ledger
    pacer: BurstPacer
    clover_top_up: int = 3_000


def probe_dir(run: ProbeRun, probe: Probe, attempt: int) -> Path:
    return run.run_dir / "probes" / f"{run.stage}-cp{probe.checkpoint}-{run.arm}" / probe.item_id / f"attempt{attempt}"


def _driver(run: ProbeRun, base: str, folder: Path, *extra: str) -> int:
    command = [
        "uv", "run", "--env-file", ".env", "python", "scripts/chat_play.py",
        "--base", base, "--cred-file", str(run.cred_file), "--cookie-file", str(run.cookie_file),
        "--log", str(folder / "chat.jsonl"), "--snapshot-log", str(folder / "memory-snapshots.jsonl"),
        "--room", str(run.room_id), *extra,
    ]  # fmt: skip
    env = {**os.environ, "DATABASE_URL": run.database_url}
    with (folder / "driver.out").open("ab") as out:
        return subprocess.run(
            command, cwd=API_DIR, env=env, stdout=out, stderr=subprocess.STDOUT, check=False
        ).returncode


def _last_turn(folder: Path) -> dict[str, Any] | None:
    path = folder / "chat.jsonl"
    if not path.exists():
        return None
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    turns = [r for r in rows if r.get("kind") == "turn"]
    return turns[-1] if turns else None


def _recall_stack(server_log: Path, offset: int) -> bool:
    if not server_log.exists():
        return False
    with server_log.open("rb") as handle:
        handle.seek(offset)
        tail = handle.read().decode(errors="replace")
    return "Traceback" in tail and "memory_recall" in tail


async def _turn_usage(database_url: str, room_id: uuid.UUID, since: datetime) -> list[dict[str, Any]]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT llm_calls FROM chat_turns WHERE chat_room_id = :room AND created_at >= :since ORDER BY created_at"
                ),
                {"room": room_id, "since": since},
            )
            return [call for (calls,) in rows for call in calls]
    finally:
        await engine.dispose()


async def _top_up(database_url: str, room_id: uuid.UUID, amount: int) -> None:
    from api.db.models import ChatRoom
    from memory_eval.room import grant_clover
    from memory_eval.runtime import make_engine

    engine, factory = make_engine(database_url)
    try:
        async with factory() as db:
            room = await db.get(ChatRoom, room_id)
            assert room is not None
            await grant_clover(db, room.user_id, amount)
    finally:
        await engine.dispose()


def run_probe(run: ProbeRun, probe: Probe) -> dict[str, Any]:
    """프로브 하나를 실패 처리 규칙대로 끝까지. 재시도는 언제나 복원부터."""
    from memory_eval import checkpoint, server
    from memory_eval.ledger import opus_turn_cost_from_usage
    from memory_eval.runtime import arm_env

    attempts: list[Attempt] = []
    records: list[dict[str, Any]] = []
    top_up = False
    while True:
        attempt_no = len(attempts) + 1
        folder = probe_dir(run, probe, attempt_no)
        folder.mkdir(parents=True, exist_ok=True)
        run.ledger.check_headroom(len(probe.turns) * (run.opus_turn_usd + run.judgment_turn_usd))
        restored = asyncio.run(
            checkpoint.restore(
                run.database_url,
                work_db=checkpoint.database_name(run.database_url),
                checkpoint=probe.checkpoint,
                room_id=run.room_id,
                dumps_dir=run.run_dir / "dumps",
            )
        )
        if top_up:
            asyncio.run(_top_up(run.database_url, run.room_id, run.clover_top_up))
        server_log = folder / "server.log"
        overrides = {
            **run.server_overrides,
            **arm_env(run.arm),
            "DATABASE_URL": run.database_url,
            "PROMPT_DUMP_PATH": str(folder / "prompt-dump.jsonl"),
        }
        started_at = datetime.now(UTC)
        handle = server.start(overrides, port=run.port, log=server_log, allow_paid=run.allow_paid)
        turns: list[dict[str, Any]] = []
        code = EXIT_OK
        try:
            code = _driver(run, handle.base, folder, "--rebase", f"체크포인트 {probe.checkpoint} 복원")
            if code == EXIT_OK:
                for text_ in probe.turns:
                    wait = run.pacer.wait_before_send(now=time.monotonic())
                    if wait:
                        time.sleep(wait)
                    run.pacer.record(time.monotonic())
                    offset = server_log.stat().st_size
                    code = _driver(run, handle.base, folder, "--say", text_, "--tag", "프로브", "--check-every", "0")
                    last = _last_turn(folder)
                    turns.append(
                        {
                            "user": text_,
                            "exit": code,
                            "reply": (last or {}).get("reply") or "",
                            "clientTurn": (last or {}).get("clientTurn"),
                        }
                    )
                    if code not in (EXIT_OK, EXIT_ENDING):
                        break
        finally:
            server.stop(handle)
        usage = asyncio.run(_turn_usage(run.database_url, run.room_id, started_at))
        for call in usage:
            run.ledger.append(
                stage=run.stage,
                call_site=str(call.get("callSite")),
                model=str(call.get("model")),
                input_tokens=int(call.get("promptTokens") or 0),
                cached_tokens=int(call.get("cachedTokens") or 0),
                cache_write_tokens=int(call.get("cacheWriteTokens") or 0),
                output_tokens=int(call.get("outputTokens") or 0),
                thoughts_tokens=int(call.get("thoughtsTokens") or 0),
                note=f"{probe.item_id} cp{probe.checkpoint} {run.arm}",
            )
        saved = len(turns) == len(probe.turns) and all(t["reply"] for t in turns)
        attempt = Attempt(exit_code=code, response_saved=saved, recall_stack=_recall_stack(server_log, 0))
        if code == EXIT_OK and not saved:
            # 드라이버는 생성 오류로 유실된 턴도 0 으로 끝낸다 — 응답이 없으면 그 밖의 오류로 센다.
            attempt = Attempt(exit_code=1, response_saved=False, recall_stack=attempt.recall_stack)
        attempts.append(attempt)
        action = next_action(attempts)
        records.append(
            {
                "attempt": attempt_no,
                "exit": attempt.exit_code,
                "saved": saved,
                "action": action.kind,
                "reason": action.reason,
                "costUsd": sum(opus_turn_cost_from_usage(c) for c in usage),
                "fingerprint": restored["fingerprint"],
                "folder": str(folder),
            }
        )
        if action.kind != "retry":
            return {
                "stage": run.stage,
                "arm": run.arm,
                "checkpoint": probe.checkpoint,
                "item": probe.item_id,
                "kind": probe.kind,
                "split": probe.split,
                "status": action.kind,
                "turns": turns,
                "attempts": records,
            }
        if action.wait_seconds:
            time.sleep(action.wait_seconds)
        top_up = action.top_up
