"""체크포인트 회상 프로브 — 계획, 실패 처리 판정, 분당 버스트 간격, 실제 실행 절차.

프로브 하나(대명사 문항은 맥락 턴 + 질문 턴 두 턴)를 보낼 때마다:
서버를 내리고, 체크포인트 템플릿으로 작업 DB 를 새로 복제하고, 이 방의 Redis 키를 정리하고, 갈래 env 로 서버를 다시 띄운다(덤프
파일은 프로브마다 하나). 첫 턴 전에 지문을 확인하고, 드라이버가 누적 기준을 새로 잡은(`--rebase`) 뒤 턴을 보내고, 응답·덤프·
사용량을 남긴다.
메시지 삭제로 프로브를 지우지 않는다 — 삭제는 스탯·엔딩·턴 수를 되돌리지 않아 다음 프로브가 앞 프로브의 판정 결과를 물려받는다.

실패 처리(결과 전 고정, 갈래를 모른 채 같은 코드가 판정한다):
- 재시도 단위는 프로브 하나 전체이고, 재시도는 언제나 복원부터 다시 한다.
- 드라이버가 4(분당 버스트 상한)로 끝나면 60초 쉬고 다시, 7(클로버 모자람)이면 채우고 다시 — 둘 다 3회까지.
- 3(엔딩 도달): 응답이 저장됐으면 그대로 채점(재시도 안 함), 저장되지 않았으면 재시도 최대 2회.
- 그 밖의 오류: 재시도 최대 2회. 단 서버 로그 스택이 회상 코드 안이면 재시도하지 않고 그 갈래의 오답으로 센다.
- 재시도를 다 쓰면 "프로브 불능". 불능이 전체 프로브의 5%를 넘으면 실행을 멈춘다.
- 장면 설정 턴이 앞서는 두 턴 프로브(비밀 문항)는 질문 턴이 체크포인트와 같은 기억 위에서 묻는지 시간에 기대지 않고 본다.
  어긋나면 재시도 없이 불능이다(같은 복원에서 다시 보내도 같은 접기가 다시 난다).
  (1) 보내기 전: 체크포인트 상태에 설정 턴·질문 턴을 차례로 더했다고 보고 접기 판정(`plan_fold`)을 돌려 어느 턴에서든
      접기가 나면, 또는 사실 추출이 끝나지 않은 스냅샷이 있으면(사실 테이블이 있을 때) 서버를 띄우지 않고 불능 — 돈을 쓰지
      않는다. 응답 글자 수는 모르므로 체크포인트 미요약 구간의 가장 긴 응답과 `ASSUMED_REPLY_CHARS` 중 큰 값으로 넉넉히 잡는다.
  (2) 보낸 뒤: 질문 턴 생성 프롬프트(덤프)에 체크포인트 요약 본문이 그대로 있는지 대조해 없으면 불능.
  (3) 보조: 둘째 턴 전에 요약 커서·사실 행 수를 몇 번 읽어 체크포인트 지문과 다르면 불능."""

import asyncio
import json
import math
import os
import re
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
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
# 두 턴 프로브의 둘째 턴 전 기억 상태 확인: 설정 턴 응답 뒤 서버 백그라운드(접기·추출)가 끝날 틈을 두고 몇 번 읽어, 그사이
# 한 번이라도 체크포인트와 달라지면 다르다고 본다.
MEMORY_GUARD_READS = 3
MEMORY_GUARD_INTERVAL_SECONDS = 2.0
# 둘째 턴 전에 체크포인트와 같아야 하는 지문 칸.
MEMORY_GUARD_FIELDS = ("cursor", "factCount", "embeddingCount")
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


def memory_drift(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[str]:
    """요약 커서·사실 행 수·임베딩 행 수 가운데 체크포인트 지문과 달라진 칸. 사실·임베딩 테이블이 없는 코드면 두 지문 모두 그
    칸이 없어 같다."""
    return [
        f"{name}: 체크포인트 {expected.get(name)!r} → 지금 {actual.get(name)!r}"
        for name in MEMORY_GUARD_FIELDS
        if expected.get(name) != actual.get(name)
    ]


EMBEDDING_INCOMPLETE = "임베딩 미완"


def embedding_incomplete(actual: Mapping[str, Any], overrides: Mapping[str, str]) -> str | None:
    """임베딩 읽기를 켠 갈래(`MEMORY_EMBED_RECALL=true`)에서 어떤 임베딩도 없는 장면·사실 행이 남았으면 그 사유. 체크포인트가
    덜 채운 채 얼려졌으면 지문이 같아 차이로는 안 잡히고, 둘째 턴의 벡터 순위가 빠진 행 없이 매겨진다. 임베딩 표가 없는 코드는
    칸이 없어 보지 않는다."""
    if overrides.get("MEMORY_EMBED_RECALL", "").strip().lower() != "true":
        return None
    left = int(actual.get("unembeddedCount") or 0)
    return f"{EMBEDDING_INCOMPLETE}: 임베딩 없는 행 {left}개" if left else None


def guard_reason(problems: Sequence[str]) -> str:
    """둘째 턴을 보내지 않은 불능 사유."""
    if any(p.startswith(EMBEDDING_INCOMPLETE) for p in problems):
        return f"둘째 턴 전 {EMBEDDING_INCOMPLETE}"
    return "둘째 턴 전 기억 상태가 체크포인트와 다르다"


# 사전 접기 판정에서 프로브 응답 하나의 글자 수 가정(실측 응답보다 넉넉하게).
ASSUMED_REPLY_CHARS = 1_500


def fold_due_offsets(unsummarized: Sequence[Any], user_texts: Sequence[str], *, reply_chars: int) -> list[int]:
    """체크포인트의 미요약 메시지 뒤에 턴(사용자 문장 + 가정 길이 응답)을 차례로 더할 때 접기가 나는 턴 순번(1부터)."""
    from api.chat.memory_fold import plan_fold
    from api.db.models import ChatMessage, ChatMessageRole

    messages = list(unsummarized)
    due = []
    for k, text_ in enumerate(user_texts, start=1):
        messages.append(ChatMessage(role=ChatMessageRole.USER, content=text_))
        messages.append(ChatMessage(role=ChatMessageRole.ASSISTANT, content="가" * reply_chars))
        if plan_fold(messages) is not None:
            due.append(k)
    return due


def assumed_reply_chars(unsummarized: Sequence[Any]) -> int:
    from api.db.models import ChatMessageRole

    longest = max((len(m.content) for m in unsummarized if m.role == ChatMessageRole.ASSISTANT), default=0)
    return max(longest, ASSUMED_REPLY_CHARS)


async def memory_precheck(database_url: str, room_id: uuid.UUID, user_texts: Sequence[str]) -> list[str]:
    """보내기 전 기억 변화 예정 사유(없으면 빈 목록): 더할 턴에서 접기가 나거나, 사실 추출이 남은 스냅샷이 있다."""
    from sqlalchemy import text

    from api.chat import memory_fold
    from api.chat.memory_window import load_current_summary
    from memory_eval.runtime import make_engine

    engine, factory = make_engine(database_url)
    try:
        async with factory() as db:
            current = await load_current_summary(db, room_id)
            unsummarized = await memory_fold._load_unsummarized(db, room_id, current.cursor if current else None)
            pending_facts = 0
            if await db.scalar(text("SELECT to_regclass('chat_memory_fact_extractions') IS NOT NULL")):
                pending_facts = int(
                    await db.scalar(
                        text(
                            "SELECT count(*) FROM chat_room_memory_snapshots s WHERE s.chat_room_id = :room AND NOT "
                            "EXISTS (SELECT 1 FROM chat_memory_fact_extractions x WHERE x.snapshot_id = s.id "
                            "AND x.status = 'done')"
                        ),
                        {"room": room_id},
                    )
                    or 0
                )
    finally:
        await engine.dispose()
    reasons = [
        f"턴 +{k} 에서 접기 예정"
        for k in fold_due_offsets(unsummarized, user_texts, reply_chars=assumed_reply_chars(unsummarized))
    ]
    if pending_facts:
        reasons.append(f"사실 추출이 남은 스냅샷 {pending_facts}개")
    return reasons


def summary_drift(folder: Path) -> list[str]:
    """질문 턴 생성 프롬프트(덤프의 마지막 생성 기록)에 체크포인트 요약(드라이버 기억 기록의 첫 요약)이 그대로 있는가.
    체크포인트 요약이 비었으면 대조할 것이 없어 빈 목록."""
    snapshots = folder / "memory-snapshots.jsonl"
    dump = folder / "prompt-dump.jsonl"
    summary = ""
    if snapshots.exists():
        for line in snapshots.read_text(encoding="utf-8").splitlines():
            if line.strip() and (row := json.loads(line)).get("kind") == "memorySnapshot":
                summary = str(row.get("summary") or "")
                break
    if not summary:
        return []
    prompts = [
        str(row.get("prompt") or "")
        for line in (dump.read_text(encoding="utf-8").splitlines() if dump.exists() else [])
        if line.strip() and (row := json.loads(line)).get("kind") == "generation"
    ]
    if not prompts:
        return ["질문 턴 생성 프롬프트 덤프가 없다"]
    return [] if summary in prompts[-1] else ["질문 턴 프롬프트의 요약이 체크포인트 요약과 다르다"]


def should_halt(unprobeable: int, total: int) -> bool:
    """불능이 계획한 프로브 전체의 5%(56개면 3)를 넘으면 멈춘다."""
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
    # 측정 서버와 이 프로세스의 복원·확인이 함께 쓰는 Redis(프로브 작업자마다 번호가 다르다). 없으면 서버 env 에 넣지 않고 이
    # 프로세스 설정의 Redis 를 쓴다 — 서버가 같은 `.env` 를 읽을 때만 둘이 같다.
    redis_url: str | None = None
    # 템플릿 → 작업 DB 복제 단계의 파일 잠금(작업자끼리 복제를 줄 세운다).
    clone_lock: Path | None = None
    # 서버를 띄우기 직전마다 부르는 검사(같은 자원을 쓰는 다른 서버가 그사이 떴는지).
    before_start: Callable[[], None] | None = None
    # 참이면 다음 시도를 시작하지 않고 `ProbeInterruptedError` 로 빠진다(병렬 실행의 멈춤 표지 — Ctrl-C 등).
    interrupted: Callable[[], bool] | None = None


class ProbeInterruptedError(Exception):
    """멈춤 표지가 서서 프로브를 끝내지 않고 빠졌다. 결과가 없으므로 결과 파일·불능 수에 들지 않고 다음 실행이 다시 돈다."""


def probe_dir(run: ProbeRun, probe: Probe, attempt: int) -> Path:
    return run.run_dir / "probes" / f"{run.stage}-cp{probe.checkpoint}-{run.arm}" / probe.item_id / f"attempt{attempt}"


def set_aside_previous_run(item_dir: Path) -> Path | None:
    """지난 실행이 남긴 문항 폴더를 `<문항>.prev-<UTC 시각>`(겹치면 `-2`, `-3` …)으로 옮긴다(없으면 None).

    시도 폴더의 서버 로그·드라이버 출력·대화 기록·프롬프트 덤프는 모두 이어 쓰기라, 다시 도는 단위가 옛 폴더에 쓰면 서버 로그의
    옛 사용량이 원장에 다시 적히고 마지막 턴·덤프·경고 집계가 옛 줄을 집는다. 지우지 않는 까닭은 지난 시도의 증거(돈을 쓴
    호출의 로그)라서다. 집계는 결과 행이 가리키는 시도 폴더만 읽으므로 옮긴 폴더는 어느 집계에도 들지 않는다."""
    if not item_dir.exists():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = item_dir.with_name(f"{item_dir.name}.prev-{stamp}")
    n = 2
    while target.exists():
        target = item_dir.with_name(f"{item_dir.name}.prev-{stamp}-{n}")
        n += 1
    item_dir.rename(target)
    return target


def _driver(run: ProbeRun, base: str, folder: Path, *extra: str) -> int:
    command = [
        "uv", "run", "--env-file", ".env", "python", "scripts/chat_play.py",
        "--base", base, "--cred-file", str(run.cred_file), "--cookie-file", str(run.cookie_file),
        "--log", str(folder / "chat.jsonl"), "--snapshot-log", str(folder / "memory-snapshots.jsonl"),
        "--room", str(run.room_id), *extra,
    ]  # fmt: skip
    env = {**os.environ, "DATABASE_URL": run.database_url, **({"REDIS_URL": run.redis_url} if run.redis_url else {})}
    # 서버와 같은 까닭으로 새 세션에서 띄운다: 터미널의 Ctrl-C 는 전경 프로세스 그룹 전체에 가므로, 같은 그룹이면 드라이버도 죽어
    # 그 시도가 그 밖의 오류로 세지고 재시도·불능으로 번진다. 중단은 하네스가 받아 다음 시도를 시작하지 않는 쪽으로만 처리한다.
    with (folder / "driver.out").open("ab") as out:
        return subprocess.run(
            command, cwd=API_DIR, env=env, stdout=out, stderr=subprocess.STDOUT, check=False, start_new_session=True
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


async def _turn_memory_facts(database_url: str, room_id: uuid.UUID, since: datetime) -> list[list[dict[str, Any]]]:
    """이 시도에서 생긴 턴 기록마다 실은 사실 행(`chat_turns.memory_facts`) — 필터 재계산이 서버가 실은 행과 견주는 입력. 작업
    DB 는 다음 복원에서 지워지므로 여기서 남긴다."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT memory_facts FROM chat_turns WHERE chat_room_id = :room AND created_at >= :since "
                    "ORDER BY created_at"
                ),
                {"room": room_id, "since": since},
            )
            return [list(facts or []) for (facts,) in rows]
    finally:
        await engine.dispose()


async def _turn_memory_recall(database_url: str, room_id: uuid.UUID, since: datetime) -> list[list[dict[str, Any]]]:
    """이 시도에서 생긴 턴 기록마다 실은 회상 줄 기록(`chat_turns.memory_recall` — 장면 id·명사 순위·벡터 순위, 본문 없음).
    벡터 쪽으로 들어온 회상 줄을 세는 입력이다. 작업 DB 는 다음 복원에서 지워지므로 여기서 남긴다."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT memory_recall FROM chat_turns WHERE chat_room_id = :room AND created_at >= :since "
                    "ORDER BY created_at"
                ),
                {"room": room_id, "since": since},
            )
            return [list(recall or []) for (recall,) in rows]
    finally:
        await engine.dispose()


async def _ensure_consent(database_url: str, room_id: uuid.UUID) -> None:
    from api.db.models import ChatRoom
    from memory_eval.room import ensure_current_consent
    from memory_eval.runtime import make_engine

    engine, factory = make_engine(database_url)
    try:
        async with factory() as db:
            room = await db.get(ChatRoom, room_id)
            assert room is not None
            await ensure_current_consent(db, [room.user_id])
            await db.commit()
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
    set_aside_previous_run(probe_dir(run, probe, 1).parent)
    while True:
        # 재시도는 복원·서버 기동부터 다시 돈다(유료) — 멈춤 표지가 섰으면 시작하지 않는다.
        if run.interrupted is not None and run.interrupted():
            raise ProbeInterruptedError(f"{probe.item_id} cp{probe.checkpoint}: 시도 {len(attempts) + 1} 전에 멈춤")
        attempt_no = len(attempts) + 1
        folder = probe_dir(run, probe, attempt_no)
        folder.mkdir(parents=True, exist_ok=True)
        # 시도마다 견적만큼 원장 자리를 잡고 서버 로그의 사용량을 원장에 적은 뒤 놓는다 — 작업자 여럿이 같은 원장을 쓸 때 상한 직전에서
        # 동시에 확인한 작업자들이 함께 통과하지 않게.
        # 실제 원가가 견적을 넘는 만큼은 막지 못하고, 그 초과분은 동시에 도는 작업자 수만큼 겹칠 수 있다.
        with run.ledger.reserve(len(probe.turns) * (run.opus_turn_usd + run.judgment_turn_usd)):
            restored = asyncio.run(
                checkpoint.restore(
                    run.database_url,
                    work_db=checkpoint.database_name(run.database_url),
                    checkpoint=probe.checkpoint,
                    room_id=run.room_id,
                    dumps_dir=run.run_dir / "dumps",
                    label=run.checkpoint_label,
                    redis_url=run.redis_url,
                    clone_lock=run.clone_lock,
                )
            )
            if top_up:
                asyncio.run(_top_up(run.database_url, run.room_id, run.clover_top_up))
            # 템플릿이 얼린 뒤 새 약관 판이 시행됐으면 측정 계정이 재동의 게이트에 막힌다 — 복원할 때마다 현행판으로 맞춘다.
            asyncio.run(_ensure_consent(run.database_url, run.room_id))
            if probe.guard_memory:
                reasons = asyncio.run(memory_precheck(run.database_url, run.room_id, probe.turns))
                if reasons:
                    records.append({"attempt": attempt_no, "action": "unprobeable", "precheck": reasons, "costUsd": 0.0,
                                    "fingerprint": restored["fingerprint"], "folder": str(folder)})  # fmt: skip
                    return {
                        "stage": run.stage, "arm": run.arm, "checkpoint": probe.checkpoint, "item": probe.item_id,
                        "kind": probe.kind, "split": probe.split, "status": "unprobeable", "turns": [],
                        "attempts": records,
                    }  # fmt: skip
            server_log = folder / "server.log"
            overrides = {
                **run.server_overrides,
                **arm_env(run.arm),
                "DATABASE_URL": run.database_url,
                "PROMPT_DUMP_PATH": str(folder / "prompt-dump.jsonl"),
                **({"REDIS_URL": run.redis_url} if run.redis_url else {}),
            }
            # 복원이 지운 전역 Voyage 멈춤 키가 그사이 다시 생겼으면 질의 임베딩이 건너뛰어진다 — 서버를 띄우기 전에 끊는다.
            asyncio.run(checkpoint.require_no_voyage_backoff(run.redis_url))
            if run.before_start is not None:
                run.before_start()
            started_at = datetime.now(UTC)
            handle = server.start(overrides, port=run.port, log=server_log, allow_paid=run.allow_paid)
            turns: list[dict[str, Any]] = []
            drift: list[str] = []
            code = EXIT_OK
            try:
                code = _driver(run, handle.base, folder, "--rebase", f"체크포인트 {probe.checkpoint} 복원")
                if code == EXIT_OK:
                    for index, text_ in enumerate(probe.turns):
                        if index > 0 and probe.guard_memory:
                            drift = _guard_memory(run, restored["fingerprint"])
                            if drift:
                                break
                        wait = run.pacer.wait_before_send(now=time.monotonic())
                        if wait:
                            time.sleep(wait)
                        run.pacer.record(time.monotonic())
                        offset = server_log.stat().st_size
                        code = _driver(
                            run, handle.base, folder, "--say", text_, "--tag", "프로브", "--check-every", "0"
                        )
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
            memory_facts = asyncio.run(_turn_memory_facts(run.database_url, run.room_id, started_at))
            memory_recall = asyncio.run(_turn_memory_recall(run.database_url, run.room_id, started_at))
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
                    note=f"{probe.item_id} cp{probe.checkpoint} {run.arm}"
                    + (" usage=missing" if call["missing"] else ""),
                )
            saved = len(turns) == len(probe.turns) and all(t["reply"] for t in turns)
            if probe.guard_memory and saved and not drift:
                drift = summary_drift(folder)
            attempt = Attempt(exit_code=code, response_saved=saved, recall_stack=recall_stack_in(log_text))
            if code == EXIT_OK and not saved:
                # 드라이버는 생성 오류로 유실된 턴도 0 으로 끝낸다 — 응답이 없으면 그 밖의 오류로 센다.
                attempt = Attempt(exit_code=1, response_saved=False, recall_stack=attempt.recall_stack)
            attempts.append(attempt)
            action = next_action(attempts)
            if drift:
                action = Action(kind="unprobeable", reason=guard_reason(drift))
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
                    "memoryDrift": drift,
                    "folder": str(folder),
                }
            )
            if action.kind != "retry":
                from api.chat.memory_vector import QUERY_EMBEDDING_CALL_SITE

                return {
                    "stage": run.stage,
                    "arm": run.arm,
                    "checkpoint": probe.checkpoint,
                    "item": probe.item_id,
                    "kind": probe.kind,
                    "split": probe.split,
                    "status": action.kind,
                    "turns": turns,
                    "memoryFacts": memory_facts,
                    "memoryRecall": memory_recall,
                    # 질의 임베딩 호출의 결과(ok·timeout·failed)와 지연 — 벡터 경로가 실제로 돌았는지 보는 입력.
                    "queryEmbeddings": [c for c in recorded_turns if c.get("callSite") == QUERY_EMBEDDING_CALL_SITE],
                    "attempts": records,
                }
        if action.wait_seconds:
            time.sleep(action.wait_seconds)
        top_up = action.top_up


def _guard_memory(run: ProbeRun, expected: Mapping[str, Any]) -> list[str]:
    """설정 턴 뒤 기억 상태를 몇 번 읽어 처음 달라진 차이(또는 임베딩 읽기 갈래의 임베딩 미완)를 돌려준다(끝까지 같으면 빈
    목록)."""
    from memory_eval import checkpoint

    for _ in range(MEMORY_GUARD_READS):
        time.sleep(MEMORY_GUARD_INTERVAL_SECONDS)
        actual = asyncio.run(checkpoint.read_fingerprint(run.database_url, run.room_id))
        drift = memory_drift(expected, actual)
        incomplete = embedding_incomplete(actual, run.server_overrides)
        if drift or incomplete:
            return [*drift, *([incomplete] if incomplete else [])]
    return []


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
# 기억을 프롬프트에 싣는 운영 자리 — 모듈 → 함수(None 이면 그 모듈 안 어디든). 장면 회상, 사실 섹션, 지식 범위 필터, 임베딩
# 회상(질의 임베딩·거리 읽기), 그리고 그것들을 부르는 생성 프롬프트 조립 함수. 이 안에서 난 오류로 끝난 응답은 그 갈래의 오답으로
# 센다. 백그라운드 추출·임베딩 채우기(`memory_facts`·`memory_episodes`·`memory_embeddings`)는 턴을 깨지 않아 넣지 않는다.
INJECTION_MODULES: dict[str, str | None] = {
    "api.chat.memory_recall": None,
    "api.chat.memory_fact_section": None,
    "api.chat.memory_knowledge": None,
    "api.chat.memory_vector": None,
    "api.chat.turn_prompt": "build_room_prompt",
}
_FRAME = re.compile(r'^\s*File "(?P<path>[^"]+)", line \d+, in (?P<function>\S+)')


def _injection_frame(line: str) -> bool:
    """스택 프레임 줄 하나가 기억 주입 자리인가 — 파일 경로 끝이 `api/chat/<모듈>.py` 와 정확히 같고, 함수를 정한 자리면 함수도
    같아야 한다(부분 문자열로 보면 비슷한 이름의 파일·다른 함수가 걸리거나 새 모듈이 빠진다)."""
    match = _FRAME.match(line)
    if match is None:
        return False
    parts = match["path"].replace("\\", "/").split("/")
    if len(parts) < 3 or not parts[-1].endswith(".py"):
        return False
    module = ".".join([*parts[-3:-1], parts[-1].removesuffix(".py")])
    if module not in INJECTION_MODULES:
        return False
    function = INJECTION_MODULES[module]
    return function is None or match["function"] == function


def recall_stack_in(text: str) -> bool:
    """스택 블록(머리줄부터 들여쓰지 않은 예외 줄까지) 안에 기억 주입 자리(`INJECTION_MODULES`) 프레임이 있는가. 블록 밖 로그
    줄의 낱말은 보지 않는다. 이 판정은 시도가 오류로 끝났을 때만 쓰인다 — 백그라운드 추출 실패는 턴을 깨지 않아 여기 오지 않는다."""
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
            if any(_injection_frame(line) for line in block):
                return True
        i += 1
    return False


# 서버 회상이 실패를 받아 회상 없이 조립할 때 남기는 경고의 고정 문구.
RECALL_WARNING = "장면 기억 회상을 읽지 못해"


def recall_warning_count(text: str) -> int:
    """서버 로그에서 회상 실패 경고 줄 수. 회상은 실패해도 턴을 깨지 않으므로 종료 코드로는 드러나지 않는다."""
    return sum(1 for line in text.splitlines() if RECALL_WARNING in line)


# 서버 사실 섹션(`chat/memory_fact_section.py` 의 `facts_for_turn`)이 실패를 받아 사실 섹션 없이 조립할 때 남기는 경고의 고정 문구.
FACT_WARNING = "관계·사실 기억을 읽지 못해"


def injection_warnings_by_arm(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """프로브 결과 행마다 모든 시도 폴더의 `server.log` 에서 사실·회상 주입 실패 경고 줄을 세어 갈래별로 모은다. 두 주입은
    실패해도 턴을 깨지 않고 그 섹션만 빼므로 응답·종료 코드로는 드러나지 않는다 — 사실을 싣는 갈래가 사실 없이 답한 턴을 가르는
    자리다. 로그가 없는 시도는 `missingLogs` 로 따로 센다(없음을 0건으로 읽지 않게)."""
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        counts = out.setdefault(
            str(row["arm"]), {"probes": 0, "fact": 0, "recall": 0, "probesWithFactWarning": 0, "missingLogs": 0}
        )
        counts["probes"] += 1
        fact_here = 0
        for attempt in row.get("attempts") or []:
            log = Path(str(attempt["folder"])) / "server.log"
            if not log.exists():
                counts["missingLogs"] += 1
                continue
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            fact_here += sum(1 for line in lines if FACT_WARNING in line)
            counts["recall"] += sum(1 for line in lines if RECALL_WARNING in line)
        counts["fact"] += fact_here
        counts["probesWithFactWarning"] += int(fact_here > 0)
    return dict(sorted(out.items()))


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
