"""측정 방의 지난 턴에서 응답 생성을 다시 부른다 — 그 턴의 실제 생성 입력(요약 + 오프닝 + 최근 원문 윈도)과, 같은
조립에서 생성 윈도만 끈 입력(대화 원문 전체, 요약 없음 — 앱이 윈도를 끄면 이렇게 조립한다), 그리고 작품 글만 보완판으로
바꿔 끼운 입력(같은 턴의 히스토리·요약·노트·스탯은 그대로)을 만든다. 기본은 프롬프트만 만들고 단언·비용 견적을 내는
시험 실행이고, `--execute` 를 줘야 LLM 을 부른다. 여러 턴을 한 번에 줄 수 있고, 모든 턴의 단언이 통과해야 호출을 시작한다.

    uv run --env-file .env python scripts/experiments/filmclub_longturn/generation_replay.py \\
        --room <id> --turn 22 --turn 105 --dump <측정>/prompt-dump.jsonl --snapshots <측정>/memory-snapshots.jsonl \\
        --turns-json <측정>/analysis/final/turns.json \\
        --variant window --variant supplement --swap-version <보완판 버전 id> --swap-table <치환 표.json> \\
        --reps 10 --limit-calls 40 --limit-usd 5 --ledger '<run>/replay/**/*.jsonl' \\
        --out <run>/replay/gen-<묶음>.jsonl [--execute]
    # 격리 DB 에 보완판 버전이 없을 때 치환 표만으로 메모리 안에서 바꿔 끼운다(도구 시험·버전 대조용):
    ... --variant window --variant supplement --swap-inmemory --swap-table <표.json> ...
    # 장부의 실제 원가 합계: replay_budget.py '<run>/replay/**/*.jsonl'

입력은 격리 DB 의 방이다. 턴 N 은 N 번째 (사용자 메시지, 바로 뒤 응답) 쌍이고, 히스토리는 그 사용자 메시지 앞의
메시지 전부다. 프롬프트는 서버의 생성 조립 함수를 그대로 불러 만들고, 지난 턴을 그때 모습으로 되살리는 세 값만 바꿔
끼운다 — 요약은 그 턴 사용자 메시지보다 먼저 만들어진 스냅샷 중 커서가 가장 큰 것(그 턴 생성 때의 현재 요약), 기억
노트는 드라이버가 그 턴 이하에서 마지막으로 남긴 노트 스냅샷(노트가 바뀐 턴에만 스냅샷이 있다), 상황 노트 조건이 읽는
스탯은 그 턴 판정 전 값(측정 분석표의 「상영회까지」 판정 전 값, 호감은 판정 뒤 값에서 그 턴 변화량을 뺀 값 — DB 에는
지금 값만 있다)이다. 방 객체는 읽자마자 세션에서 떼어 내고 나서 바꾸므로 DB 에는 쓰이지 않고, CLI 는 읽기 전용
트랜잭션 안에서만 조립한다. `window` 입력은 서버가 그 턴에 덤프한 프롬프트·지시문과 바이트까지 같아야 하고, 다르면
실행하지 않는다 — 다르면 되살린 조립이 틀린 것이라 다른 갈래도 믿을 수 없다.

`supplement` 갈래는 방의 버전만 보완판 버전으로 바꿔(시작설정도 그 버전에서 다시 찾는다) 같은 조립을 부른다. 스탯은
측정값 그대로 쓴다(보완판의 단계 노트 문턱이 같아 같은 노트가 실린다). 치환 표로 두 겹을 단언한다(역치환 바이트 일치와
그 턴에 실려야 할 칸마다 실제 치환 발생 — `supplement_swap.py`). `--swap-inmemory` 는 버전을 바꾸지 않고 그 턴에 읽은
v6-fix 행의 글을 치환 표대로 메모리 안에서만 바꾼다(행을 고친 것으로 표시하지 않아 flush 대상이 아니다).

호출: 앱의 생성 클라이언트(`GeminiLLMClient.generate`, 스트리밍)를 같은 지시문·같은 중단 문자열로 부른다 — 모델·출력
상한·사고 설정·타임아웃이 실제 생성과 같다. call_site 는 리플레이 전용 라벨 `replay_generate` 라 사용량 집계가 측정
대화와 섞이지 않는다(앱의 call_site 목록에 없는 라벨이라 어느 판정 집합에도 들지 않고, 생성 모델·생성 타임아웃을
받는다). 호출 수는 `--limit-calls` 하드 상한을, 실제 원가 누적(`--ledger` 의 앞 묶음 포함)은 `--limit-usd` 를 넘지
않는다(원가 상한은 마지막 한 호출만큼 넘을 수 있다). 호출 기록마다 실제 토큰으로 계산한 `costUsd` 를 남긴다.
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
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from api.chat import router
from api.chat.memory_window import CurrentSummary, MessageKey, prompt_window
from api.chat.prompt_builder import load_active_prompt_set
from api.chat.router import _build_prompt, _require_starting_setup
from api.core.config import settings
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom, ChatRoomMemorySnapshot
from api.db.models.story import KeywordNote, SituationNote, StartingSetup, StoryVersionDetail
from api.llm.client import LLMCallContext, LLMCallSite, LLMClient
from api.llm.gemini import GeminiLLMClient
from api.llm.pricing import estimate_cost_usd

# 스크립트로 실행할 때도 `scripts/` 를 패키지 기준으로 둔다(pytest·mypy 와 같은 모듈 경로).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.filmclub_longturn.replay_budget import CallBudget, ledger_paths, sum_ledger
from experiments.filmclub_longturn.supplement_swap import (
    SwapSlot,
    check_swap,
    load_swap_table,
    replace_in_value,
)

# 측정 분석표는 「상영회까지」만 판정 전 값(`countdownBefore`)을 따로 적고, 호감은 판정 뒤 값과 변화량으로 적는다.
COUNTDOWN_STAT = "상영회까지"

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


@dataclass(frozen=True)
class SwapSpec:
    """`supplement` 갈래의 바꿔 끼우기 — 보완판 버전 id(격리 DB 에 얹은 버전) 또는 메모리 안 치환(`version_id` 없음)."""

    slots: list[SwapSlot]
    version_id: uuid.UUID | None = None


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


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def note_for_turn(path: Path, room_id: uuid.UUID, turn: int) -> str:
    """드라이버 기억 스냅샷에서 그 턴 전송 때 방에 있던 노트 — 그 턴 이하에서 가장 늦은 스냅샷. 드라이버는 노트를 바꾼
    턴에만 스냅샷을 남기므로 그 사이 턴은 앞 스냅샷의 노트를 그대로 쓴다. 그 턴 이하 스냅샷이 없거나 가장 늦은 턴에
    스냅샷이 둘 이상이면 멈춘다."""
    found = [
        record
        for record in _jsonl(path)
        if record.get("kind") == "memorySnapshot"
        and record.get("roomId") == str(room_id)
        and record.get("turn") is not None
        and record["turn"] <= turn
    ]
    if not found:
        raise ValueError(f"턴 {turn} 이하의 기억 스냅샷이 없다")
    latest = max(record["turn"] for record in found)
    at_latest = [record for record in found if record["turn"] == latest]
    if len(at_latest) != 1:
        raise ValueError(f"턴 {latest} 의 기억 스냅샷이 {len(at_latest)}개다")
    return str(at_latest[0]["note"])


def stat_ids_by_name(path: Path, room_id: uuid.UUID) -> dict[str, str]:
    """드라이버 기억 스냅샷 파일의 `roomStatic` 에서 스탯 이름 → entity_id. 재개마다 다시 적히므로 모두 같아야 한다."""
    mappings = [
        {stat["name"]: stat["id"] for stat in record["stats"]}
        for record in _jsonl(path)
        if record.get("kind") == "roomStatic" and record.get("roomId") == str(room_id)
    ]
    if not mappings:
        raise ValueError("스냅샷 파일에 roomStatic 이 없다")
    if any(mapping != mappings[0] for mapping in mappings):
        raise ValueError("roomStatic 의 스탯 목록이 기록마다 다르다")
    return mappings[0]


def stats_before_turn(turns_path: Path, ids_by_name: dict[str, str], turn: int) -> dict[str, float]:
    """측정 분석표(`turns.json`)에서 그 턴 판정 전 스탯 값(entity_id → 값). 생성은 판정보다 먼저라 상황 노트 조건은 이
    값으로 봤다. 분석표가 그 턴의 모든 스탯을 덮지 못하면 멈춘다."""
    rows = {row["turn"]: row for row in json.loads(turns_path.read_text(encoding="utf-8"))}
    if turn not in rows:
        raise ValueError(f"분석표에 턴 {turn} 이 없다")
    row = rows[turn]
    values: dict[str, float] = {}
    for name, stat_id in ids_by_name.items():
        if name == COUNTDOWN_STAT:
            values[stat_id] = float(row["countdownBefore"])
        else:
            values[stat_id] = float(row["affection"][name]) - float(row["affectionDelta"][name])
    return values


@contextlib.contextmanager
def room_stats_asof(values: dict[str, float] | None) -> Iterator[None]:
    """이 프로세스에서만 생성 조립이 읽는 방 스탯의 지금 값을 `values` 로 덮는다(정의·행은 DB 그대로). `None` 이면 그대로."""
    if values is None:
        yield
        return
    saved = getattr(router, "_load_room_stats")  # noqa: B009 — 비공개 이름이라 mypy 가 속성 접근을 막는다

    async def load_asof(db: AsyncSession, room_id: uuid.UUID, setup_id: uuid.UUID) -> tuple[Any, Any, dict[str, float]]:
        stat_defs, stat_rows, current = await saved(db, room_id, setup_id)
        missing = {str(stat_def.entity_id) for stat_def in stat_defs} - set(values)
        if missing:
            raise ValueError(f"판정 전 값이 없는 스탯: {sorted(missing)}")
        return stat_defs, stat_rows, {**current, **values}

    try:
        setattr(router, "_load_room_stats", load_asof)  # noqa: B010 — 모듈 함수 대입은 mypy 가 막는다
        yield
    finally:
        setattr(router, "_load_room_stats", saved)  # noqa: B010


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


_DETAIL_TEXT_FIELDS = ("setting_text", "development_examples", "user_goal", "rules", "custom_prompt")


async def _build_swapped_prompt(
    db: AsyncSession,
    room: ChatRoom,
    setup: StartingSetup,
    swap: SwapSpec,
    history: list[ChatMessage],
    user_content: str,
    prompt_set: Any,
    sections: Any,
) -> tuple[str, str]:
    """보완판 작품 글로 같은 턴의 생성 프롬프트를 만든다. `room` 은 세션에서 떼어 낸 객체여야 한다.

    버전이 있으면 방의 버전만 바꾸고 시작설정을 그 버전에서 다시 찾는다(시작설정·노트·스탯 정의는 버전마다 새 행이고
    entity_id 로 이어진다). 없으면 그 턴에 읽힌 v6-fix 행(상세·시작설정·키워드 노트·상황 노트)의 글을 치환 표대로 바꾼 값을
    `set_committed_value` 로 얹는다 — 바뀐 것으로 표시되지 않아 flush 가 쓰지 않고, 끝나면 원래 값으로 되돌린다. 표의
    칸이 그 행들 어디에도 없으면 멈춘다(표의 v6-fix 문안이 틀렸다)."""
    if swap.version_id is not None:
        original_version = room.content_version_id
        room.content_version_id = swap.version_id
        try:
            swapped_setup = await _require_starting_setup(db, room)
            if swapped_setup is None:
                raise ValueError("보완판 버전에서 방의 시작설정을 찾지 못했다")
            prompt, system_instruction, *_ = await _build_prompt(
                db, room, swapped_setup, history, user_content, None, prompt_set, sections
            )
        finally:
            room.content_version_id = original_version
        return prompt, system_instruction

    detail = await db.get(StoryVersionDetail, room.content_version_id)
    assert detail is not None
    keyword_notes = (
        await db.scalars(select(KeywordNote).where(KeywordNote.content_version_id == room.content_version_id))
    ).all()
    situation_notes = (await db.scalars(select(SituationNote).where(SituationNote.starting_setup_id == setup.id))).all()
    targets: list[tuple[Any, str]] = [(detail, name) for name in _DETAIL_TEXT_FIELDS]
    targets += [(setup, "prologue")]
    targets += [(note, "info_text") for note in [*keyword_notes, *situation_notes]]
    hits: dict[str, int] = {}
    restore: list[tuple[Any, str, Any]] = []
    try:
        for obj, name in targets:
            before = getattr(obj, name)
            after = replace_in_value(before, swap.slots, hits)
            if after != before:
                restore.append((obj, name, before))
                set_committed_value(obj, name, after)
        absent = [slot.key for slot in swap.slots if not hits.get(slot.key)]
        if absent:
            raise ValueError(f"치환 표의 v6-fix 문안을 작품 글에서 찾지 못한 칸: {absent}")
        prompt, system_instruction, *_ = await _build_prompt(
            db, room, setup, history, user_content, None, prompt_set, sections
        )
    finally:
        for obj, name, before in restore:
            set_committed_value(obj, name, before)
    return prompt, system_instruction


async def build_generation_inputs(
    db: AsyncSession,
    room_id: uuid.UUID,
    turn: int,
    *,
    variants: list[str],
    memory_note: str | None = None,
    stats_before: dict[str, float] | None = None,
    swap: SwapSpec | None = None,
) -> list[GenerationInput]:
    if "supplement" in variants and swap is None:
        raise ValueError("supplement 갈래는 바꿔 끼울 버전 또는 메모리 안 치환 표가 있어야 한다")
    room = await db.get(ChatRoom, room_id)
    if room is None:
        raise ValueError(f"방이 없다: {room_id}")
    # 무엇이든 바꾸기 전에 세션에서 떼어 낸다 — 붙은 채로 바꾸면 다음 쿼리의 autoflush 가 방 행에 쓴다.
    db.expunge(room)
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
        room.memory_note = memory_note
    inputs: list[GenerationInput] = []
    for variant in variants:
        window = variant in ("window", "supplement")
        with generation_state(summary, window=window), room_stats_asof(stats_before):
            if variant == "supplement":
                assert swap is not None
                prompt, system_instruction = await _build_swapped_prompt(
                    db, room, setup, swap, history, user.content, prompt_set, sections
                )
            else:
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
                sink({**budget.exhausted(), "turn": item.turn, "variant": item.variant, "rep": rep})
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
            record = {
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
            budget.charge(record)
            record["cumulativeChargedUsd"] = round(budget.spent_usd, 6)
            sink(record)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _first_difference(a: str, b: str) -> int:
    return next((i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y), min(len(a), len(b)))


async def _plan_turn(
    args: argparse.Namespace, room_id: uuid.UUID, turn: int, swap: SwapSpec | None, ids_by_name: dict[str, str]
) -> tuple[dict[str, Any], list[GenerationInput]]:
    """한 턴의 입력을 만들고 단언 결과를 담은 계획 기록을 낸다. 조립은 읽기 전용 트랜잭션 안에서만 한다."""
    from api.db.session import async_session_factory

    dumped, dump_count = dump_record(Path(args.dump), room_id, turn)
    note = note_for_turn(Path(args.snapshots), room_id, turn)
    stats = stats_before_turn(Path(args.turns_json), ids_by_name, turn)
    async with async_session_factory() as db:
        await db.execute(sql_text("SET TRANSACTION READ ONLY"))
        inputs = await build_generation_inputs(
            db, room_id, turn, variants=args.variant, memory_note=note, stats_before=stats, swap=swap
        )
        await db.rollback()
    checks: dict[str, Any] = {"dumpRecords": dump_count, "dumpPromptSha256": _sha(dumped["prompt"])}
    by_variant = {item.variant: item for item in inputs}
    window = by_variant.get("window")
    if window is not None:
        checks["windowPromptIdentical"] = window.prompt == dumped["prompt"]
        checks["windowSystemInstructionIdentical"] = window.system_instruction == dumped["systemInstruction"]
        if not checks["windowPromptIdentical"]:
            checks["firstDifferenceAt"] = _first_difference(window.prompt, dumped["prompt"])
    supplement = by_variant.get("supplement")
    if supplement is not None and window is not None and swap is not None:
        row = {r["turn"]: r for r in json.loads(Path(args.turns_json).read_text(encoding="utf-8"))}[turn]  # noqa: ASYNC240 — 한 번 쓰는 CLI
        checks["swap"] = check_swap(
            base_prompt=window.prompt,
            base_system=window.system_instruction,
            swapped_prompt=supplement.prompt,
            swapped_system=supplement.system_instruction,
            slots=swap.slots,
            situation_notes=row["situationNotes"],
            keyword_notes=row["keywordNotes"],
        )
    model = settings.gemini_model_name
    input_tokens = [round((len(i.prompt) + len(i.system_instruction)) / CHARS_PER_TOKEN) for i in inputs]
    per_round = sum(
        estimate_cost_usd(model, input_tokens=t, cached_tokens=0, output_tokens=OUTPUT_TOKENS, thoughts_tokens=0) or 0.0
        for t in input_tokens
    )
    plan = {
        "kind": "plan",
        "at": datetime.now(UTC).isoformat(),
        "roomId": str(room_id),
        "turn": turn,
        "execute": args.execute,
        "model": model,
        "callSite": REPLAY_CALL_SITE,
        "reps": args.reps,
        "estimatedUsd": round(per_round * args.reps, 4),
        "swapVersion": str(swap.version_id) if swap is not None and swap.version_id else None,
        "swapInMemory": swap is not None and swap.version_id is None,
        "statsBefore": {name: stats[stat_id] for name, stat_id in ids_by_name.items()},
        "checks": checks,
        "inputs": [
            {
                "variant": i.variant,
                "historyMessages": i.history_messages,
                "promptChars": len(i.prompt),
                "systemInstructionChars": len(i.system_instruction),
                "promptSha256": _sha(i.prompt),
                "estimatedInputTokens": tokens,
            }
            for i, tokens in zip(inputs, input_tokens, strict=True)
        ],
    }
    return plan, inputs


def plan_passed(plan: dict[str, Any], variants: list[str]) -> bool:
    checks = plan["checks"]
    if "window" in variants and not (
        checks.get("windowPromptIdentical") and checks.get("windowSystemInstructionIdentical")
    ):
        return False
    return not ("supplement" in variants and not checks.get("swap", {}).get("passed"))


async def _main(args: argparse.Namespace) -> int:
    from api.db.session import async_session_factory

    room_id = uuid.UUID(args.room)
    if "supplement" in args.variant and "window" not in args.variant:
        print("supplement 갈래는 같은 턴의 window 입력과 대조해야 한다 — --variant window 도 준다")
        return 1
    swap: SwapSpec | None = None
    if "supplement" in args.variant:
        if not args.swap_table or bool(args.swap_version) == bool(args.swap_inmemory):
            print("supplement 갈래는 --swap-table 과, --swap-version 또는 --swap-inmemory 중 하나가 있어야 한다")
            return 1
        swap = SwapSpec(
            slots=load_swap_table(Path(args.swap_table)),
            version_id=uuid.UUID(args.swap_version) if args.swap_version else None,
        )
    async with async_session_factory() as db:
        room = await db.get(ChatRoom, room_id)
        if room is None:
            print(f"방이 없다: {room_id}")
            return 1
        user_id = room.user_id
        await db.rollback()
    ids_by_name = stat_ids_by_name(Path(args.snapshots), room_id)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    def sink(record: dict[str, Any]) -> None:
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    all_inputs: list[GenerationInput] = []
    failed: list[int] = []
    for turn in args.turn:
        plan, inputs = await _plan_turn(args, room_id, turn, swap, ids_by_name)
        sink(plan)
        print(
            json.dumps(
                {"turn": turn, "checks": plan["checks"], "estimatedUsd": plan["estimatedUsd"]}, ensure_ascii=False
            )
        )
        if args.prompt_out:
            for item in inputs:
                Path(f"{args.prompt_out}.t{turn:03d}.{item.variant}.txt").write_text(item.prompt, encoding="utf-8")  # noqa: ASYNC240 — 한 번 쓰는 CLI
        if not plan_passed(plan, args.variant):
            failed.append(turn)
        all_inputs.extend(inputs)
    if failed:
        print(f"단언 실패 턴 {failed} — 되살린 조립이나 바꿔 끼우기가 틀렸으니 실행하지 않는다")
        return 2
    spent = sum_ledger(ledger_paths(args.ledger)).charged_usd if args.ledger else 0.0
    planned = min(len(all_inputs) * args.reps, args.limit_calls)
    print(
        json.dumps(
            {"turns": len(args.turn), "plannedCalls": planned, "ledgerChargedUsd": round(spent, 6)}, ensure_ascii=False
        )
    )
    if not args.execute:
        print("시험 실행 — LLM 을 부르지 않았다(--execute 로 실행)")
        return 0
    if args.limit_usd is not None and spent >= args.limit_usd:
        print(f"장부 누적 ${spent:.4f} 가 이미 상한 ${args.limit_usd} 이상이다 — 부르지 않는다")
        return 3
    client = GeminiLLMClient()
    capture: dict[str, Any] = {}
    install_stream_capture(client, capture)
    budget = CallBudget(args.limit_calls, usd_limit=args.limit_usd, spent_usd=spent)
    room_ref = ChatRoom(id=room_id, user_id=user_id)
    await run_generation_replay(client, capture, all_inputs, reps=args.reps, budget=budget, room=room_ref, sink=sink)
    print(json.dumps({"calls": budget.used, "cumulativeChargedUsd": round(budget.spent_usd, 6)}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", required=True)
    ap.add_argument("--turn", type=int, action="append", required=True, help="방 턴 번호(N 번째 완결 턴, 여럿 가능)")
    ap.add_argument("--dump", required=True, help="서버 프롬프트 덤프(PROMPT_DUMP_PATH) — window 입력 대조용")
    ap.add_argument("--snapshots", required=True, help="드라이버 기억 스냅샷(memory-snapshots.jsonl) — 노트·스탯 이름")
    ap.add_argument(
        "--turns-json", required=True, help="측정 분석표(analysis/final/turns.json) — 판정 전 스탯·노트 이름"
    )
    ap.add_argument("--variant", action="append", choices=["window", "full", "supplement"], required=True)
    ap.add_argument("--swap-version", help="supplement: 격리 DB 에 얹은 보완판 버전 id")
    ap.add_argument("--swap-inmemory", action="store_true", help="supplement: 버전 없이 치환 표로 메모리 안에서 바꾼다")
    ap.add_argument("--swap-table", help="supplement: 치환 표 JSON(칸 키·v6-fix 문안·보완판 문안·실림 조건)")
    ap.add_argument("--prompt-out", help="만든 프롬프트를 이 접두 경로에 저장(<접두>.tNNN.<variant>.txt)")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--limit-calls", type=int, required=True, help="이 실행의 실호출 하드 상한")
    ap.add_argument("--limit-usd", type=float, help="장부 포함 실제 원가 누적 상한(달러)")
    ap.add_argument("--ledger", help="앞 묶음 호출 기록 glob(재귀 **) — 실제 원가를 상한에 넣는다")
    ap.add_argument("--out", required=True)
    ap.add_argument("--execute", action="store_true", help="LLM 을 실제로 부른다")
    return asyncio.run(_main(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
