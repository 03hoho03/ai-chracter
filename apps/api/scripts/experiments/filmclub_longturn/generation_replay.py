"""측정 방의 한 턴에서 응답 생성을 다시 부른다 — 그 턴의 실제 생성 입력(요약 + 오프닝 + 최근 원문 윈도)과, 같은
조립에서 생성 윈도만 끈 입력(대화 원문 전체, 요약 없음 — 앱이 윈도를 끄면 이렇게 조립한다)을 나란히 보내, 회상이
틀린 원인이 원문이 윈도 밖으로 빠진 데 있는지 모델 자체에 있는지 가른다. 기본은 프롬프트만 만들고 비용 견적을 내는
시험 실행이고, `--execute` 를 줘야 LLM 을 부른다.

    uv run --env-file .env python scripts/experiments/filmclub_longturn/generation_replay.py \\
        --room <id> --turn <방 턴 번호> --dump <run>/prompt-dump.jsonl --snapshots <run>/memory-snapshots.jsonl \\
        --variant window --variant full --reps 5 --limit-calls 10 --out <run>/replay/t<NNN>-gen.jsonl [--execute]

입력은 격리 DB 의 방이다. 턴 N 은 N 번째 (사용자 메시지, 바로 뒤 응답) 쌍이고, 히스토리는 그 사용자 메시지 앞의
메시지 전부다. 프롬프트는 서버의 생성 조립 함수를 그대로 불러 만들고, 지난 턴을 그때 모습으로 되살리는 두 값만 바꿔
끼운다 — 요약은 그 턴 사용자 메시지보다 먼저 만들어진 스냅샷 중 커서가 가장 큰 것(그 턴 생성 때의 현재 요약),
기억 노트는 드라이버가 그 턴 전송 직전에 남긴 노트 스냅샷이다(방에는 지금 노트만 있다). 방 객체는 세션에서 떼어 낸
뒤 노트를 바꾸므로 DB 에는 쓰이지 않는다. `window` 입력은 서버가 그 턴에 덤프한 프롬프트·지시문과 바이트까지 같아야
하고, 다르면 실행하지 않는다 — 다르면 되살린 조립이 틀린 것이라 `full` 입력도 믿을 수 없다.

호출: 앱의 생성 클라이언트(`GeminiLLMClient.generate`, 스트리밍)를 같은 지시문·같은 중단 문자열로 부른다 — 모델·출력
상한·사고 설정·타임아웃이 실제 생성과 같다. call_site 는 리플레이 전용 라벨 `replay_generate` 라 사용량 집계가 측정
대화와 섞이지 않는다(앱의 call_site 목록에 없는 라벨이라 어느 판정 집합에도 들지 않고, 생성 모델·생성 타임아웃을
받는다). 호출 수는 `--limit-calls` 하드 상한을 넘지 않는다.
"""

import argparse
import asyncio
import contextlib
import hashlib
import json
import sys
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import router
from api.chat.memory_window import CurrentSummary, MessageKey, prompt_window
from api.chat.prompt_builder import load_active_prompt_set
from api.chat.router import _build_prompt, _require_starting_setup
from api.core.config import settings
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom, ChatRoomMemorySnapshot
from api.llm.client import LLMCallContext, LLMCallSite, LLMClient
from api.llm.gemini import GeminiLLMClient
from api.llm.pricing import estimate_cost_usd

REPLAY_CALL_SITE = cast(LLMCallSite, "replay_generate")
# 견적용 — 한국어 생성 프롬프트는 글자 2개에 토큰 1개 안팎이라 넉넉히 잡는다. 출력은 사고 토큰 포함 상한 쪽으로 잡는다.
CHARS_PER_TOKEN = 1.6
OUTPUT_TOKENS = 2_500


@dataclass(frozen=True)
class GenerationInput:
    variant: str
    turn: int
    prompt: str
    system_instruction: str
    user_label: str
    history_messages: int
    call_site: LLMCallSite = REPLAY_CALL_SITE


class CallBudget:
    """프로세스 전체의 실호출 상한."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


def dump_record(path: Path, room_id: uuid.UUID, turn: int) -> tuple[dict[str, Any], int]:
    """서버 덤프에서 그 방·그 턴의 마지막 기록과 기록 수. 유실·재시도 턴은 같은 턴 번호로 여러 번 덤프되고, 응답이 남은
    것은 마지막 시도다."""
    found = [
        record
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for record in [json.loads(line)]
        if record.get("roomId") == str(room_id) and record.get("turn") == turn
    ]
    if not found:
        raise ValueError(f"덤프에 턴 {turn} 이 없다")
    return found[-1], len(found)


def note_for_turn(path: Path, room_id: uuid.UUID, turn: int) -> str:
    """드라이버 기억 스냅샷에서 그 턴 전송 직전의 노트. 없거나 둘 이상이면 멈춘다."""
    found = [
        record
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for record in [json.loads(line)]
        if record.get("kind") == "memorySnapshot"
        and record.get("roomId") == str(room_id)
        and record.get("turn") == turn
    ]
    if len(found) != 1:
        raise ValueError(f"턴 {turn} 의 기억 스냅샷이 {len(found)}개다")
    return str(found[0]["note"])


async def summary_asof(db: AsyncSession, room_id: uuid.UUID, before: datetime) -> CurrentSummary | None:
    """`before` 보다 먼저 만들어진 스냅샷 중 커서가 가장 큰 것 — 그 시각의 현재 요약(서버의 "현재" 규칙과 같은 정렬)."""
    row = (
        await db.execute(
            select(
                ChatRoomMemorySnapshot.cursor_created_at,
                ChatRoomMemorySnapshot.cursor_message_id,
                ChatRoomMemorySnapshot.summary_text,
            )
            .where(ChatRoomMemorySnapshot.chat_room_id == room_id, ChatRoomMemorySnapshot.created_at < before)
            .order_by(ChatRoomMemorySnapshot.cursor_created_at.desc(), ChatRoomMemorySnapshot.cursor_message_id.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    cursor: MessageKey = (row.cursor_created_at, row.cursor_message_id)
    return CurrentSummary(cursor=cursor, text=row.summary_text)


@contextlib.contextmanager
def generation_state(summary: CurrentSummary | None, *, window: bool) -> Iterator[None]:
    """이 프로세스에서만 생성 윈도 설정과 생성 조립이 읽는 "현재 요약"을 바꾼다."""
    saved_flag = settings.memory_window_generation
    saved_loader = getattr(router, "load_current_summary")  # noqa: B009 — 재수출하지 않는 이름이라 mypy 가 속성 접근을 막는다

    async def load_asof(_db: AsyncSession, _room_id: uuid.UUID) -> CurrentSummary | None:
        return summary

    try:
        settings.memory_window_generation = window
        setattr(router, "load_current_summary", load_asof)  # noqa: B010 — 모듈 함수 대입은 mypy 가 막는다
        yield
    finally:
        settings.memory_window_generation = saved_flag
        setattr(router, "load_current_summary", saved_loader)  # noqa: B010


def _turn_pairs(messages: list[ChatMessage]) -> list[int]:
    """턴 번호(1부터) → 그 턴 사용자 메시지의 인덱스. 바로 뒤가 응답인 사용자 메시지만 턴이다."""
    return [
        index
        for index in range(len(messages) - 1)
        if messages[index].role == ChatMessageRole.USER and messages[index + 1].role == ChatMessageRole.ASSISTANT
    ]


async def build_generation_inputs(
    db: AsyncSession,
    room_id: uuid.UUID,
    turn: int,
    *,
    variants: list[str],
    memory_note: str | None = None,
) -> list[GenerationInput]:
    room = await db.get(ChatRoom, room_id)
    if room is None:
        raise ValueError(f"방이 없다: {room_id}")
    setup = await _require_starting_setup(db, room)
    if setup is None:
        raise ValueError("스토리 방만 리플레이한다")
    messages = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room.id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            )
        ).all()
    )
    pairs = _turn_pairs(messages)
    if not 1 <= turn <= len(pairs):
        raise ValueError(f"턴 {turn} 이 없다(완결 턴 {len(pairs)}개)")
    index = pairs[turn - 1]
    history, user = messages[:index], messages[index]
    summary = await summary_asof(db, room.id, user.created_at)
    prompt_set, sections = await load_active_prompt_set(db, lane="story")
    if memory_note is not None:
        # 세션에서 떼어 낸 뒤 바꾼다 — 붙은 채로 바꾸면 다음 쿼리의 autoflush 가 방 행에 노트를 쓴다.
        db.expunge(room)
        room.memory_note = memory_note
    inputs: list[GenerationInput] = []
    for variant in variants:
        window = variant == "window"
        with generation_state(summary, window=window):
            prompt, system_instruction, *_ = await _build_prompt(
                db, room, setup, history, user.content, None, prompt_set, sections
            )
        shown = prompt_window(history, summary.cursor) if window and summary is not None else history
        inputs.append(
            GenerationInput(
                variant=variant,
                turn=turn,
                prompt=prompt,
                system_instruction=system_instruction,
                user_label=prompt_set.user_label,
                history_messages=len(shown),
            )
        )
    return inputs


_TOKEN_FIELDS = {
    "prompt": "prompt_token_count",
    "cached": "cached_content_token_count",
    "candidates": "candidates_token_count",
    "thoughts": "thoughts_token_count",
    "total": "total_token_count",
}


def install_stream_capture(client: GeminiLLMClient, capture: dict[str, Any]) -> None:
    """`client` 의 SDK 스트리밍 호출을 감싸 실제로 보낸 모델·설정과 마지막 토큰 메타데이터·종료 사유를 `capture` 에
    담는다. 보내는 값은 바꾸지 않는다."""
    models = client._client.aio.models
    original = models.generate_content_stream

    async def generate_content_stream(**kwargs: Any) -> AsyncIterator[Any]:
        config = kwargs.get("config")
        capture["sent_model"] = kwargs.get("model")
        capture["sent_timeout_ms"] = getattr(getattr(config, "http_options", None), "timeout", None)
        capture["sent_thinking"] = getattr(config, "thinking_config", None) is not None
        stream = await original(**kwargs)

        async def relay() -> AsyncIterator[Any]:
            async for chunk in stream:
                usage = getattr(chunk, "usage_metadata", None)
                if usage is not None:
                    capture["tokens"] = {key: getattr(usage, attr, None) for key, attr in _TOKEN_FIELDS.items()}
                for candidate in getattr(chunk, "candidates", None) or []:
                    if candidate.finish_reason is not None:
                        capture["finish_reason"] = str(
                            getattr(candidate.finish_reason, "name", candidate.finish_reason)
                        )
                yield chunk

        return relay()

    setattr(models, "generate_content_stream", generate_content_stream)  # noqa: B010


def _cost(model: str | None, tokens: dict[str, Any] | None) -> float | None:
    if model is None or not tokens:
        return None
    return estimate_cost_usd(
        model,
        input_tokens=tokens.get("prompt") or 0,
        cached_tokens=tokens.get("cached") or 0,
        output_tokens=tokens.get("candidates") or 0,
        thoughts_tokens=tokens.get("thoughts") or 0,
    )


async def run_generation_replay(
    client: LLMClient,
    capture: dict[str, Any],
    inputs: list[GenerationInput],
    *,
    reps: int,
    budget: CallBudget,
    room: ChatRoom,
    sink: Callable[[dict[str, Any]], None],
) -> None:
    for item in inputs:
        for rep in range(reps):
            if not budget.take():
                sink({"kind": "budgetExhausted", "limit": budget.limit, "variant": item.variant, "rep": rep})
                return
            capture.clear()
            started = time.perf_counter()
            chunks: list[str] = []
            error: str | None = None
            try:
                async for delta in client.generate(
                    item.prompt,
                    item.system_instruction,
                    stop_sequences=[f"\n{item.user_label}:"],
                    usage=LLMCallContext(call_site=item.call_site, user_id=room.user_id, room_id=room.id),
                ):
                    chunks.append(delta)
            except Exception as exc:  # 기록하고 다음 호출로 — 실패(정책 차단 등)도 결과다
                error = f"{type(exc).__name__}: {str(exc)[:500]}"
            tokens = capture.get("tokens")
            sink(
                {
                    "kind": "call",
                    "at": datetime.now(UTC).isoformat(),
                    "turn": item.turn,
                    "variant": item.variant,
                    "rep": rep,
                    "callSite": item.call_site,
                    "sentModel": capture.get("sent_model"),
                    "sentTimeoutMs": capture.get("sent_timeout_ms"),
                    "sentThinkingConfig": capture.get("sent_thinking"),
                    "tokens": tokens,
                    "costUsd": _cost(capture.get("sent_model"), tokens),
                    "finishReason": capture.get("finish_reason"),
                    "latencyMs": round((time.perf_counter() - started) * 1000, 1),
                    "historyMessages": item.history_messages,
                    "promptChars": len(item.prompt),
                    "promptSha256": hashlib.sha256(item.prompt.encode()).hexdigest()[:16],
                    "reply": "".join(chunks),
                    "error": error,
                }
            )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _first_difference(a: str, b: str) -> int:
    return next((i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y), min(len(a), len(b)))


async def _main(args: argparse.Namespace) -> int:
    from api.db.session import async_session_factory

    room_id = uuid.UUID(args.room)
    dumped, dump_count = dump_record(Path(args.dump), room_id, args.turn)
    note = note_for_turn(Path(args.snapshots), room_id, args.turn) if args.snapshots else None
    async with async_session_factory() as db:
        room = await db.get(ChatRoom, room_id)
        if room is None:
            print(f"방이 없다: {room_id}")
            return 1
        user_id, turn_count = room.user_id, room.turn_count
        inputs = await build_generation_inputs(db, room_id, args.turn, variants=args.variant, memory_note=note)
        await db.rollback()
    checks: dict[str, Any] = {"dumpRecords": dump_count, "dumpPromptSha256": _sha(dumped["prompt"])}
    for item in inputs:
        if item.variant != "window":
            continue
        checks["windowPromptIdentical"] = item.prompt == dumped["prompt"]
        checks["windowSystemInstructionIdentical"] = item.system_instruction == dumped["systemInstruction"]
        if not checks["windowPromptIdentical"]:
            checks["firstDifferenceAt"] = _first_difference(item.prompt, dumped["prompt"])
    model = settings.gemini_model_name
    input_tokens = [round((len(i.prompt) + len(i.system_instruction)) / CHARS_PER_TOKEN) for i in inputs]
    per_round = 0.0
    for tokens in input_tokens:
        cost = estimate_cost_usd(
            model, input_tokens=tokens, cached_tokens=0, output_tokens=OUTPUT_TOKENS, thoughts_tokens=0
        )
        per_round += cost or 0.0
    estimate = per_round * args.reps
    plan_inputs = [
        {
            "variant": i.variant,
            "historyMessages": i.history_messages,
            "promptChars": len(i.prompt),
            "systemInstructionChars": len(i.system_instruction),
            "promptSha256": _sha(i.prompt),
            "estimatedInputTokens": tokens,
        }
        for i, tokens in zip(inputs, input_tokens, strict=True)
    ]
    plan = {
        "kind": "plan",
        "at": datetime.now(UTC).isoformat(),
        "roomId": str(room_id),
        "roomTurnCount": turn_count,
        "turn": args.turn,
        "execute": args.execute,
        "model": model,
        "callSite": REPLAY_CALL_SITE,
        "reps": args.reps,
        "calls": min(len(inputs) * args.reps, args.limit_calls),
        "estimatedUsd": round(estimate, 4),
        "memoryNoteFromSnapshot": note is not None,
        "checks": checks,
        "inputs": plan_inputs,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.prompt_out:
        for item in inputs:
            Path(f"{args.prompt_out}.{item.variant}.txt").write_text(item.prompt, encoding="utf-8")  # noqa: ASYNC240 — 한 번 쓰는 CLI

    def sink(record: dict[str, Any]) -> None:
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    sink(plan)
    print(json.dumps(plan, ensure_ascii=False))
    if "window" in args.variant and not (
        checks.get("windowPromptIdentical") and checks.get("windowSystemInstructionIdentical")
    ):
        print("window 입력이 덤프와 다르다 — 되살린 조립이 틀렸으니 실행하지 않는다")
        return 2
    if not args.execute:
        print("시험 실행 — LLM 을 부르지 않았다(--execute 로 실행)")
        return 0
    client = GeminiLLMClient()
    capture: dict[str, Any] = {}
    install_stream_capture(client, capture)
    room_ref = ChatRoom(id=room_id, user_id=user_id)
    await run_generation_replay(
        client, capture, inputs, reps=args.reps, budget=CallBudget(args.limit_calls), room=room_ref, sink=sink
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", required=True)
    ap.add_argument("--turn", type=int, required=True, help="방 턴 번호(N 번째 완결 턴)")
    ap.add_argument("--dump", required=True, help="서버 프롬프트 덤프(PROMPT_DUMP_PATH) — window 입력 대조용")
    ap.add_argument("--snapshots", help="드라이버 기억 스냅샷(memory-snapshots.jsonl) — 그 턴 당시 기억 노트")
    ap.add_argument("--variant", action="append", choices=["window", "full"], required=True)
    ap.add_argument("--prompt-out", help="만든 프롬프트를 이 접두 경로에 저장(<접두>.<variant>.txt)")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--limit-calls", type=int, required=True, help="실호출 하드 상한")
    ap.add_argument("--out", required=True)
    ap.add_argument("--execute", action="store_true", help="LLM 을 실제로 부른다")
    return asyncio.run(_main(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
