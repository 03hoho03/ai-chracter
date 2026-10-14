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
import math
import os
import re
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
    # 복원할 체크포인트 템플릿의 단계 이름(얼린 넣기 실행의 label — 기준선 s4, 최종 비교 s8).
    checkpoint_label: str = ""
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


def _server_log_text(server_log: Path) -> str:
    return server_log.read_text(encoding="utf-8", errors="replace") if server_log.exists() else ""


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
                label=run.checkpoint_label,
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
                            # 드라이버가 잰 첫 글자 지연(보낸 뒤 첫 token 이벤트까지, ms). 첫 글자 전에 끊기면 None.
                            "ttftMs": (last or {}).get("ttftMs"),
                        }
                    )
                    if code not in (EXIT_OK, EXIT_ENDING):
                        break
        finally:
            server.stop(handle)
        log_text = _server_log_text(server_log)
        # 원장 기준은 서버 로그(실패한 시도·백그라운드 접기·추출 포함). 턴 기록은 생성 호출 수 대조에만 쓴다.
        usage = parse_usage_log(log_text)
        recorded_turns = asyncio.run(_turn_usage(run.database_url, run.room_id, started_at))
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
                note=f"{probe.item_id} cp{probe.checkpoint} {run.arm}" + (" usage=missing" if call["missing"] else ""),
            )
        saved = len(turns) == len(probe.turns) and all(t["reply"] for t in turns)
        attempt = Attempt(exit_code=code, response_saved=saved, recall_stack=recall_stack_in(log_text))
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
                "costUsd": sum(opus_turn_cost_from_usage(c) for c in usage if not c["missing"]),
                "usageMissing": sum(1 for c in usage if c["missing"]),
                "usageProviders": sorted({str(c["provider"]) for c in usage}),
                "recallWarnings": recall_warning_count(log_text),
                "generateCallsLog": sum(1 for c in usage if c["callSite"] == "chat_generate"),
                "generateCallsTurns": sum(1 for c in recorded_turns if c.get("callSite") == "chat_generate"),
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


def pending_probes(probes: Sequence[Probe], done: Sequence[dict[str, Any]]) -> tuple[list[Probe], int]:
    """재실행: 결과 파일에 이미 있는 (체크포인트, 문항)은 건너뛰고, 그 파일의 불능 수부터 이어 센다."""
    finished = {(int(r["checkpoint"]), str(r["item"])) for r in done}
    todo = [p for p in probes if (p.checkpoint, p.item_id) not in finished]
    return todo, sum(1 for r in done if r.get("status") == "unprobeable")


_USAGE_LINE = re.compile(r"\b(anthropic|gemini|bedrock)_usage\s+(.*)$")
_USAGE_FIELDS = {
    "prompt_tokens": "promptTokens",
    "cached_content_tokens": "cachedTokens",
    "cache_write_tokens": "cacheWriteTokens",
    "candidates_tokens": "outputTokens",
    "thoughts_tokens": "thoughtsTokens",
}


def _int_or_none(raw: str | None) -> int | None:
    return int(raw) if raw is not None and raw.isdigit() else None


def parse_usage_log(text: str) -> list[dict[str, Any]]:
    """서버 로그의 사용량 줄(`anthropic_usage`·`gemini_usage`·`bedrock_usage`) — 실패한 시도와 백그라운드 접기·추출까지
    서버가 실제로 부른 호출 전부다. 원장은 이것을 기준으로 적고 턴 기록(`chat_turns.llm_calls`)은 대조에만 쓴다(둘을 더하면
    같은 호출이 두 번 세진다). 메타데이터가 없는 줄은 `missing` 으로 표시한다."""
    calls = []
    for line in text.splitlines():
        match = _USAGE_LINE.search(line)
        if match is None:
            continue
        fields = dict(part.split("=", 1) for part in match.group(2).split() if "=" in part)
        call: dict[str, Any] = {
            "provider": match.group(1),
            "callSite": fields.get("call_site"),
            "model": fields.get("model"),
        }
        for raw, name in _USAGE_FIELDS.items():
            call[name] = _int_or_none(fields.get(raw))
        call["missing"] = fields.get("usage") == "missing" or call["promptTokens"] is None
        calls.append(call)
    return calls


_TRACEBACK = "Traceback (most recent call last):"


def recall_stack_in(text: str) -> bool:
    """스택 블록(머리줄부터 들여쓰지 않은 예외 줄까지) 안에 회상 모듈 프레임이 있는가. 블록 밖 로그 줄의 낱말은 보지 않는다."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith(_TRACEBACK):
            block = [lines[i]]
            i += 1
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                block.append(lines[i])
                i += 1
            if i < len(lines):
                block.append(lines[i])  # 예외 줄
            if any("memory_recall" in line for line in block if line.lstrip().startswith("File ")):
                return True
        i += 1
    return False


# 서버 회상이 실패를 받아 회상 없이 조립할 때 남기는 경고의 고정 문구.
RECALL_WARNING = "장면 기억 회상을 읽지 못해"


def recall_warning_count(text: str) -> int:
    """서버 로그에서 회상 실패 경고 줄 수. 회상은 실패해도 턴을 깨지 않으므로 종료 코드로는 드러나지 않는다."""
    return sum(1 for line in text.splitlines() if RECALL_WARNING in line)


def percentile(values: Sequence[float], p: float) -> float | None:
    """가장 가까운 순위 백분위수: 정렬한 값의 ceil(p/100 · n) 번째. 값이 없으면 None."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return float(ordered[rank - 1])


def probe_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """프로브 결과 요약: 갈래별 상태 수와 첫 글자 지연(ms) p50·p95. 지연은 받아들인(accept) 프로브의 턴 가운데 드라이버가
    지연을 잰 턴만 센다 — 재시도 끝에 불능이 된 프로브의 턴은 서버 상태가 다른 시도라 섞지 않는다."""
    out: dict[str, Any] = {}
    for arm in sorted({str(r["arm"]) for r in rows}):
        members = [r for r in rows if str(r["arm"]) == arm]
        status: dict[str, int] = {}
        for r in members:
            status[str(r["status"])] = status.get(str(r["status"]), 0) + 1
        ttft = [
            float(t["ttftMs"])
            for r in members
            if r["status"] == "accept"
            for t in r.get("turns", [])
            if t.get("ttftMs") is not None
        ]
        out[arm] = {
            "probes": len(members),
            "status": status,
            "ttftTurns": len(ttft),
            "ttftP50Ms": percentile(ttft, 50),
            "ttftP95Ms": percentile(ttft, 95),
        }
    return out
