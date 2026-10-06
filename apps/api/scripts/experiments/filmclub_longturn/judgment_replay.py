"""측정 방의 한 턴에서 미디어 북 칸 판정·엔딩 판정·스탯 판정을 다시 부른다 — 실제 판정은 요약이 덮은 원문을 빼고(판정
윈도) 불렸으니, 같은 턴을 대화 전체로 불러 결과가 갈리는지 본다. 스탯 판정은 히스토리를 싣지 않아 윈도와 무관하고,
같은 입력을 여러 번 보내 한 번 나온 판정 값이 다시 나오는지(재현성)를 본다. 기본은 프롬프트만 만들고 비용 견적을 내는
시험 실행이고, `--execute` 를 줘야 LLM 을 부른다.

    uv run --env-file .env python scripts/experiments/filmclub_longturn/judgment_replay.py \\
        --room <id> --turn <방 턴 번호> --kind image --kind ending [--ending <엔딩 entity_id>] \\
        [--variant full|window] [--reps 3] [--limit-calls 6] --out <run>/replay/t<NNN>.jsonl [--execute]
    # 스탯 판정: 그 턴의 시작 값을 서버 trace 의 stat_outcome 에서 읽는다(DB 에는 지금 값만 있다).
    ... --kind stat --stat-start-trace <run>/trace.jsonl --reps 10 --limit-calls 10 ...
    # 스탯 줄 형식 비교: 같은 입력을 현행·수정안 형식으로 만들어 갈래마다 reps 번 보낸다(아래 STAT_FORMATS).
    ... --kind stat --stat-format current --stat-format A --stat-format L --stat-format B ...
    # 오프라인 입력(스탯 판정만): DB 없이 입력 JSON(extract_stat_inputs.py 가 만든다)과 레인 섹션 파일로 조립한다.
    ... --input-json <입력>.json [--input-json …] --sections-json <운영 stat_judgment 섹션>.json \\
        --stat-format current --stat-format A --stat-format L --stat-format B --prompt-dir <디렉터리> ...

입력은 격리 DB 의 방이다(오프라인 입력은 아래 「오프라인 입력」). 턴 N 은 N 번째 (사용자 메시지, 바로 뒤 응답) 쌍이고, 판정 입력의 히스토리는 그 사용자 메시지
앞의 메시지 전부다(유실 턴의 사용자 메시지도 서버가 그랬듯 히스토리에 든다). 프롬프트는 서버의 판정 준비 함수를 그대로
불러 만든다 — 판정 윈도 설정만 이 프로세스 안에서 끄거나 켠다. `window` 는 방의 현재 요약을 쓰므로 방의 마지막 턴에만
허용한다. `window-asof` 는 칸 판정만, 아무 턴에나 쓴다 — 그 턴 사용자 메시지보다 먼저 만들어진 요약 스냅샷 중 커서가 가장 큰
것(그 턴 판정 때의 현재 요약)으로 서버와 같은 윈도를 씌운다. 요약은 턴이 끝난 뒤 접히므로 그 턴 판정 때 있던 스냅샷은
사용자 메시지보다 먼저 생긴 것뿐이다. 칸 판정은 요약 본문을 싣지 않아 커서만 있으면 된다. 엔딩은 그 턴에 판정할 차례(게이트·5턴 간격)인 엔딩만 만들고,
스탯 규칙은 보지 않는다 — 실제로 판정이 불린 엔딩을 `--ending` 으로 고른다. 스탯 판정 프롬프트는 서버와 같은
빌더·같은 스탯 정의 순서로 만들고 현재값만 trace 의 시작 값으로 넣는다. 결과마다 서버 적용 규칙(방향·폭·범위)을 거친
값도 함께 남긴다.

오프라인 입력: 원천마다 DB 스키마와 활성 프롬프트 세트가 달라 방에서 바로 조립하면 원천마다 문안이 달라진다. 그래서
입력마다 스탯 정의·그 턴 시작값·사용자 메시지·응답·이름을 JSON 으로 뽑아 두고, 레인 섹션(채널 `stat_judgment`)과 라벨은
파일 하나에서 받아 서버 `build_stat_judgment_prompt` 로 조립한다 — 모든 입력이 같은 문안 위에서 비교된다. L 갈래는
지시문 섹션 본문 끝에 공백 한 칸과 문장을 붙여 렌더하고, 그것이 현행 프롬프트 끝에 같은 것을 붙인 문자열과 같은지
확인한다(레인 문안으로 게시하는 형태와 리플레이 형태가 같다는 확인 — 지시문이 마지막 섹션일 때만 성립한다).

모델·타임아웃·집계: 리플레이 call_site 는 앱의 판정 집합에 들어 있어 원래 판정과 같은 모델로 가고(시작할 때 같은지
확인하고 다르면 멈춘다), 운영 판정과 다른 라벨이라 사용량·로그가 섞이지 않는다. 수십만 토큰 비스트리밍 호출이라 판정
상한에 잘리지 않게, SDK 호출 직전에 요청 단위 타임아웃을 `REPLAY_TIMEOUT_MS` 로 덮는다. 같은 자리에서 실제로 보낸
모델·타임아웃·토큰을 담는다. 호출 수는 `--limit-calls` 하드 상한을 넘지 않는다.
"""

import argparse
import asyncio
import contextlib
import hashlib
import json
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.genai import types as genai_types
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import MessageKey, load_current_summary, prompt_window
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    PromptNames,
    StatJudgmentResult,
    _stat_line_tail,
    build_ending_judgment_prompt,
    build_stat_judgment_prompt,
    load_active_prompt_set,
)
from api.chat.router import (
    _build_prompt,
    _load_due_endings,
    _load_room_stats,
    _prepare_media_cell_judgment,
    _require_starting_setup,
)
from api.chat.stats import StatChange, apply_stat_changes
from api.core.config import settings
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom, ChatRoomMemorySnapshot
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import StatDef
from api.llm.client import LLMCallContext, LLMCallSite, LLMClient, structured_model
from api.llm.gemini import GeminiLLMClient
from api.llm.pricing import estimate_cost_usd

REPLAY_TIMEOUT_MS = 300_000
# 리플레이 call_site → 원래 판정 call_site. 모델이 같아야 "윈도 vs 전체" 대조에 모델 차이가 섞이지 않는다.
REPLAY_SITES: dict[str, tuple[LLMCallSite, LLMCallSite]] = {
    "stat": ("replay_stat_judgment", "chat_stat_judgment"),
    "image": ("replay_media_book_image", "chat_media_book_image"),
    "ending": ("replay_ending_judgment", "chat_ending_judgment"),
}
# 견적: 전체 히스토리 판정 입력이 턴당 약 450 토큰씩 자란다는 추정치로 낸다(실측 아님 — 시험 실행 기록의 실제 프롬프트
# 글자 수와 함께 본다. window 변형에는 과대 견적이다). 출력은 짧은 JSON 이다.
TOKENS_PER_TURN = 450
OUTPUT_TOKENS = 60
# 스탯 판정은 히스토리가 없어 턴과 무관하다. 측정 방 서버 로그의 스탯 판정 입력이 1,700 토큰대라 넉넉히 잡는다.
STAT_INPUT_TOKENS = 2_000

# 스탯 판정 프롬프트 형식 갈래. 판정이 한 호감의 새 값을 다른 호감의 현재값 기준으로 내는 오독을 줄이는지 본다.
# current = 서버 출력 그대로. A = 스탯 줄에서 현재값·범위를 이름 바로 뒤로, 긴 작가 설명을 줄 끝으로 옮긴다(서버 줄은
# 현재값이 설명 뒤 꼬리에 있어 이름에서 수백 자 떨어진다 — 줄 형식은 코드라 운영 반영은 코드 변경이다). L = 현행 줄에
# 지시문 끝 한 문장(기준은 자기 현재값)을 덧붙인다 — 지시문은 레인 섹션이라 운영 반영은 문안 게시만으로 된다. B = A + L.
STAT_FORMATS = ("current", "A", "L", "B")
BASELINE_SENTENCE = (
    "newValue는 그 statId 줄에 적힌 그 스탯 자신의 현재값에 이번 턴의 변화만큼 더하거나 빼서 정하라. "
    "다른 스탯의 현재값을 기준으로 삼지 마라."
)


@dataclass(frozen=True)
class ReplayInput:
    kind: str
    variant: str
    turn: int
    prompt: str
    schema: type[BaseModel]
    call_site: LLMCallSite
    original_call_site: LLMCallSite
    history_messages: int
    ending_id: uuid.UUID | None = None
    candidate_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    # 스탯 판정만: 서버 적용 규칙을 다시 돌릴 정의와 그 턴의 시작 값.
    stat_defs: tuple[StatDef, ...] = ()
    stat_start: dict[str, float] = field(default_factory=dict)
    stat_format: str = "current"
    # 오프라인 입력만: 입력 파일의 id 와 검증 군.
    input_id: str | None = None
    group: str | None = None


@dataclass(frozen=True)
class OfflineOwner:
    """오프라인 입력 호출의 사용량 귀속 — DB 방이 없어 원천 방 id 만 적고 사용자는 비운다."""

    id: uuid.UUID
    user_id: uuid.UUID | None = None


def _stat_value(stat_def: StatDef, current_stats: dict[str, float]) -> float:
    return current_stats.get(str(stat_def.entity_id), stat_def.initial_value)


def _server_stat_lines(stat_defs: list[StatDef], current_stats: dict[str, float], names: PromptNames) -> str:
    """서버 `build_stat_judgment_prompt` 의 스탯 줄을 같은 식으로 복제한다. 복제가 서버와 어긋나면 프롬프트에서 찾지
    못해 `stat_prompt_variant` 가 멈춘다."""
    return "\n".join(
        f"- statId={stat_def.entity_id}, 이름={names.expand(stat_def.name)}, "
        f"설명={names.expand(stat_def.description)}, "
        f"범위=[{stat_def.min_value}, {stat_def.max_value}], "
        f"현재값={_stat_value(stat_def, current_stats)}" + _stat_line_tail(stat_def)
        for stat_def in stat_defs
    )


def _value_first_stat_lines(stat_defs: list[StatDef], current_stats: dict[str, float], names: PromptNames) -> str:
    return "\n".join(
        f"- statId={stat_def.entity_id}, 이름={names.expand(stat_def.name)}, "
        f"현재값={_stat_value(stat_def, current_stats)}, "
        f"범위=[{stat_def.min_value}, {stat_def.max_value}], "
        f"설명={names.expand(stat_def.description)}" + _stat_line_tail(stat_def)
        for stat_def in stat_defs
    )


def stat_prompt_variant(
    prompt: str, stat_defs: list[StatDef], current_stats: dict[str, float], names: PromptNames, stat_format: str
) -> str:
    """서버가 만든 스탯 판정 프롬프트를 `stat_format` 갈래로 바꾼다. 스탯 줄 밖(사용자 이름·이번 턴·지시문)은 그대로
    두고, 지시문 문장은 프롬프트 끝(마지막 섹션이 지시문이다)에 덧붙인다."""
    if stat_format == "current":
        return prompt
    if stat_format in ("A", "B"):
        server_lines = _server_stat_lines(stat_defs, current_stats, names)
        if prompt.count(server_lines) != 1:
            raise ValueError("서버 스탯 줄을 프롬프트에서 정확히 한 번 찾지 못했다 — 서버 줄 형식이 복제와 다르다")
        prompt = prompt.replace(server_lines, _value_first_stat_lines(stat_defs, current_stats, names))
    if stat_format in ("L", "B"):
        prompt = f"{prompt} {BASELINE_SENTENCE}"
    if stat_format not in STAT_FORMATS:
        raise ValueError(f"모르는 스탯 형식: {stat_format}")
    return prompt


class CallBudget:
    """프로세스 전체의 실호출 상한. `take` 와 그 앞의 검사 사이에 await 가 없어 동시 호출끼리도 넘지 않는다."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


@contextlib.contextmanager
def judgment_window(enabled: bool) -> Iterator[None]:
    """이 프로세스에서만 판정 윈도 설정을 바꾼다. 생성 윈도는 판정 윈도의 전제라 켜진 상태여야 한다."""
    keys = ("memory_window_image_judgment", "memory_window_ending_judgment")
    saved = {key: getattr(settings, key) for key in keys}
    if enabled and not settings.memory_window_generation:
        raise ValueError("생성 윈도가 꺼져 있으면 판정 윈도도 쓰이지 않는다")
    try:
        for key in keys:
            setattr(settings, key, enabled)
        yield
    finally:
        for key, value in saved.items():
            setattr(settings, key, value)


def stat_start_from_trace(path: Path, room_id: uuid.UUID, turn: int) -> dict[str, float]:
    """서버 trace 의 `stat_outcome` 에서 그 방·그 턴 판정의 시작 값(statId → start). 없거나 둘 이상이면 멈춘다 — 다른
    턴의 값을 쓰면 재구성 프롬프트가 실제와 달라진다."""
    found = [
        record
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for record in [json.loads(line)]
        if record.get("kind") == "stat_outcome" and record.get("roomId") == str(room_id) and record.get("turn") == turn
    ]
    if not found:
        raise ValueError(f"trace 에 턴 {turn} 의 stat_outcome 이 없다")
    if len(found) > 1:
        raise ValueError(f"trace 에 턴 {turn} 의 stat_outcome 이 {len(found)}개다")
    return {stat["statId"]: float(stat["start"]) for stat in found[0]["stats"]}


async def snapshot_cursor_asof(db: AsyncSession, room_id: uuid.UUID, before: datetime) -> MessageKey | None:
    """`before` 보다 먼저 만들어진 스냅샷 중 커서가 가장 큰 것의 커서 — 그 시각의 현재 요약(서버의 "현재" 규칙과 같은
    정렬)."""
    row = (
        await db.execute(
            select(ChatRoomMemorySnapshot.cursor_created_at, ChatRoomMemorySnapshot.cursor_message_id)
            .where(ChatRoomMemorySnapshot.chat_room_id == room_id, ChatRoomMemorySnapshot.created_at < before)
            .order_by(ChatRoomMemorySnapshot.cursor_created_at.desc(), ChatRoomMemorySnapshot.cursor_message_id.desc())
            .limit(1)
        )
    ).first()
    return None if row is None else (row.cursor_created_at, row.cursor_message_id)


def _turn_pairs(messages: list[ChatMessage]) -> list[int]:
    """턴 번호(1부터) → 그 턴 사용자 메시지의 인덱스. 바로 뒤가 응답인 사용자 메시지만 턴이다(유실 턴은 방 턴 수에
    세지 않는다)."""
    return [
        index
        for index in range(len(messages) - 1)
        if messages[index].role == ChatMessageRole.USER and messages[index + 1].role == ChatMessageRole.ASSISTANT
    ]


async def build_inputs(
    db: AsyncSession,
    room_id: uuid.UUID,
    turn: int,
    *,
    kinds: list[str],
    variant: str,
    ending_ids: list[uuid.UUID] | None = None,
    stat_start: dict[str, float] | None = None,
    stat_formats: list[str] | None = None,
) -> list[ReplayInput]:
    room = await db.get(ChatRoom, room_id)
    if room is None:
        raise ValueError(f"방이 없다: {room_id}")
    setup = await _require_starting_setup(db, room)
    if setup is None:
        raise ValueError("스토리 방만 리플레이한다")
    if variant == "window" and turn != room.turn_count:
        raise ValueError(f"window 는 방의 마지막 턴({room.turn_count})에만 쓸 수 있다")
    if variant == "window-asof" and kinds != ["image"]:
        raise ValueError("window-asof 는 칸 판정(image)만 만든다 — 엔딩 판정은 그때의 요약 본문도 싣는다")
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
    history, user, assistant = messages[:index], messages[index], messages[index + 1]
    prompt_set, sections = await load_active_prompt_set(db, lane="story")
    names = (await _build_prompt(db, room, setup, history, user.content, None, prompt_set, sections))[4]
    windowed = variant == "window"
    window_count = len(history)
    if windowed:
        summary = await load_current_summary(db, room.id)
        if summary is not None:
            window_count = len(prompt_window(history, summary.cursor))
    judged_history = history
    if variant == "window-asof":
        # 판정 윈도를 끈 채 미리 씌운 히스토리를 넘긴다 — 서버가 켠 상태에서 하는 `prompt_window(history, 커서)` 와 같다.
        judged_history = prompt_window(history, await snapshot_cursor_asof(db, room.id, user.created_at))
        window_count = len(judged_history)

    inputs: list[ReplayInput] = []
    if "stat" in kinds:
        stat_defs, _, _ = await _load_room_stats(db, room.id, setup.id)
        expected = {str(stat_def.entity_id) for stat_def in stat_defs}
        if stat_start is None or set(stat_start) != expected:
            raise ValueError("스탯 판정은 그 턴의 시작 값이 스탯마다 있어야 한다(DB 에는 지금 값만 있다)")
        site, original = REPLAY_SITES["stat"]
        server_prompt = build_stat_judgment_prompt(
            prompt_set=prompt_set,
            sections=sections,
            stat_defs=stat_defs,
            current_stats=stat_start,
            user_message=user.content,
            assistant_message=assistant.content,
            names=names,
        )
        for stat_format in stat_formats or ["current"]:
            inputs.append(
                ReplayInput(
                    kind="stat",
                    variant=variant,
                    turn=turn,
                    prompt=stat_prompt_variant(server_prompt, stat_defs, stat_start, names, stat_format),
                    schema=StatJudgmentResult,
                    call_site=site,
                    original_call_site=original,
                    history_messages=0,
                    stat_defs=tuple(stat_defs),
                    stat_start=dict(stat_start),
                    stat_format=stat_format,
                )
            )
    with judgment_window(windowed):
        if "image" in kinds:
            judgment = await _prepare_media_cell_judgment(
                db,
                room,
                prompt_set=prompt_set,
                prompt_sections=sections,
                history=judged_history,
                user_message=user.content,
                assistant_message=assistant.content,
                names=names,
            )
            if judgment is not None:
                site, original = REPLAY_SITES["image"]
                inputs.append(
                    ReplayInput(
                        kind="image",
                        variant=variant,
                        turn=turn,
                        prompt=judgment.prompt,
                        schema=ImageMatchJudgmentResult,
                        call_site=site,
                        original_call_site=original,
                        history_messages=window_count,
                        candidate_ids=frozenset(judgment.candidate_ids),
                    )
                )
        if "ending" in kinds:
            due = await _load_due_endings(db, room, setup, history, turn)
            for ending, _rules in due.endings:
                if ending_ids and ending.entity_id not in ending_ids:
                    continue
                site, original = REPLAY_SITES["ending"]
                inputs.append(
                    ReplayInput(
                        kind="ending",
                        variant=variant,
                        turn=turn,
                        prompt=build_ending_judgment_prompt(
                            prompt_set=prompt_set,
                            sections=sections,
                            judgment_prompt=ending.judgment_prompt,
                            history=due.history,
                            user_message=user.content,
                            assistant_message=assistant.content,
                            memory_summary=due.summary,
                            names=names,
                        ),
                        schema=EndingJudgmentResult,
                        call_site=site,
                        original_call_site=original,
                        history_messages=len(due.history),
                        ending_id=ending.entity_id,
                    )
                )
    return inputs


def check_same_models(inputs: list[ReplayInput], default_model: str) -> dict[str, str]:
    """리플레이 call_site 가 원래 판정과 같은 모델을 고르는지. 다르면 대조가 무의미하므로 멈춘다."""
    models: dict[str, str] = {}
    for item in inputs:
        replay_model = structured_model(item.call_site, default_model)
        original_model = structured_model(item.original_call_site, default_model)
        if replay_model != original_model:
            raise ValueError(f"{item.call_site} 모델 {replay_model} ≠ {item.original_call_site} 모델 {original_model}")
        models[item.call_site] = replay_model
    return models


def estimate(inputs: list[ReplayInput], reps: int, models: dict[str, str]) -> dict[str, Any]:
    calls = len(inputs) * reps
    total = 0.0
    for item in inputs:
        cost = estimate_cost_usd(
            models[item.call_site],
            input_tokens=_input_tokens(item),
            cached_tokens=0,
            output_tokens=OUTPUT_TOKENS,
            thoughts_tokens=0,
        )
        total += (cost or 0.0) * reps
    return {
        "calls": calls,
        "estimatedUsd": round(total, 4),
        "tokensPerCall": [_input_tokens(i) for i in inputs],
    }


def _input_tokens(item: ReplayInput) -> int:
    return STAT_INPUT_TOKENS if item.kind == "stat" else TOKENS_PER_TURN * item.turn


def stat_result(item: ReplayInput, output: StatJudgmentResult) -> list[dict[str, Any]]:
    """원 출력에 서버와 같은 적용 규칙(같은 스탯은 마지막 항목, 방향·폭·범위)을 돌린 스탯별 결과."""
    changes = [StatChange(stat_id=c.stat_id, new_value=c.new_value) for c in output.stat_changes]
    applied = apply_stat_changes(item.stat_start, changes, list(item.stat_defs))
    requested = {c.stat_id: c.new_value for c in changes}
    return [
        {
            "statId": str(stat_def.entity_id),
            "name": stat_def.name,
            "start": item.stat_start[str(stat_def.entity_id)],
            "requested": requested.get(str(stat_def.entity_id)),
            "applied": applied[str(stat_def.entity_id)],
        }
        for stat_def in item.stat_defs
    ]


# ── 오프라인 입력 ────────────────────────────────────────────────────────────


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def load_sections(path: Path) -> tuple[PromptSet, list[PromptSection]]:
    """레인 섹션 파일(`stat_judgment_sections` + `labels`)을 세션 없는 행으로 읽는다. 본문·라벨이 파일에 적힌 md5·글자
    수와 다르면 멈춘다 — 손으로 고친 사본이 운영 문안으로 행세하지 않게."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    labels = payload["labels"]
    for key in ("user_label", "story_assistant_label"):
        if f"{key}_md5" in labels and _md5(labels[key]) != labels[f"{key}_md5"]:
            raise ValueError(f"라벨 {key} 의 md5 가 파일에 적힌 값과 다르다")
    sections: list[PromptSection] = []
    for row in payload["stat_judgment_sections"]:
        if _md5(row["body"]) != row["md5"] or len(row["body"]) != row["length"]:
            raise ValueError(f"섹션 {row['slot']} 본문이 파일에 적힌 md5·길이와 다르다")
        sections.append(
            PromptSection(
                channel="stat_judgment",
                scope=row["scope"],
                slot=row["slot"],
                variant=row["variant"],
                order=row["order"],
                conditional=row["conditional"],
                body=row["body"],
            )
        )
    prompt_set = PromptSet(user_label=labels["user_label"], story_assistant_label=labels["story_assistant_label"])
    return prompt_set, sections


def with_baseline_sentence(sections: list[PromptSection]) -> list[PromptSection]:
    """지시문 섹션 본문 끝에 공백 한 칸 + 문장 — 운영 레인 문안에 게시할 형태 그대로."""
    targets = [s for s in sections if s.slot == "judgment_instruction"]
    if len(targets) != 1:
        raise ValueError(f"judgment_instruction 섹션이 {len(targets)}개다")
    return [
        PromptSection(
            channel=s.channel,
            scope=s.scope,
            slot=s.slot,
            variant=s.variant,
            order=s.order,
            conditional=s.conditional,
            body=f"{s.body} {BASELINE_SENTENCE}" if s.slot == "judgment_instruction" else s.body,
        )
        for s in sections
    ]


def offline_stat_defs(data: dict[str, Any]) -> list[StatDef]:
    """입력 파일의 스탯 정의를 서버가 읽은 순서(`serverIndex`) 그대로 세션 없는 행으로."""
    rows = data["statDefs"]
    if [row["serverIndex"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"{data['inputId']}: 스탯 정의가 서버 순서로 적혀 있지 않다")
    return [
        StatDef(
            entity_id=uuid.UUID(row["entity_id"]),
            name=row["name"],
            description=row["description"],
            min_value=row["min_value"],
            max_value=row["max_value"],
            initial_value=row["initial_value"],
            per_turn_delta=row["per_turn_delta"],
            change_direction=row["change_direction"],
            max_change_per_turn=row["max_change_per_turn"],
            order=row["order"],
        )
        for row in rows
    ]


def build_offline_inputs(
    data: dict[str, Any], prompt_set: PromptSet, sections: list[PromptSection], stat_formats: list[str]
) -> list[ReplayInput]:
    """입력 JSON 한 개 → 갈래별 스탯 판정 입력. 시작값이 스탯마다 있어야 하고(빠지면 서버가 초기값을 넣어 실제와
    달라진다), L 갈래의 섹션 렌더가 현행 + `" "` + 문장과 바이트 단위로 같아야 한다."""
    stat_defs = offline_stat_defs(data)
    stat_start = {str(k): float(v) for k, v in data["statStart"].items()}
    if set(stat_start) != {str(d.entity_id) for d in stat_defs}:
        raise ValueError(f"{data['inputId']}: 시작값이 스탯 정의와 맞지 않는다")
    names = PromptNames(
        persona_name=data["names"]["personaName"],
        default_user_name=data["names"]["defaultUserName"],
        char_name=None,
    )
    if names.judgment_user_name != data["names"]["userNameLine"]:
        raise ValueError(f"{data['inputId']}: 이름 한 줄 값이 입력 파일과 다르다")

    def render(rendered_sections: list[PromptSection]) -> str:
        return build_stat_judgment_prompt(
            prompt_set=prompt_set,
            sections=rendered_sections,
            stat_defs=stat_defs,
            current_stats=stat_start,
            user_message=data["userMessage"],
            assistant_message=data["assistantMessage"],
            names=names,
        )

    current = render(sections)
    with_sentence = render(with_baseline_sentence(sections))
    if with_sentence != f"{current} {BASELINE_SENTENCE}":
        raise ValueError(
            f"{data['inputId']}: 문장을 붙인 섹션 렌더가 현행 + 문장과 다르다(지시문이 마지막 섹션이 아니다)"
        )
    prompts = {fmt: stat_prompt_variant(current, stat_defs, stat_start, names, fmt) for fmt in STAT_FORMATS}
    if (
        prompts["L"] != with_sentence
        or stat_prompt_variant(with_sentence, stat_defs, stat_start, names, "A") != prompts["B"]
    ):
        raise ValueError(f"{data['inputId']}: L·B 갈래가 섹션 렌더와 다르다")
    site, original = REPLAY_SITES["stat"]
    return [
        ReplayInput(
            kind="stat",
            variant="offline",
            turn=int(data["turn"]),
            prompt=prompts[fmt],
            schema=StatJudgmentResult,
            call_site=site,
            original_call_site=original,
            history_messages=0,
            stat_defs=tuple(stat_defs),
            stat_start=dict(stat_start),
            stat_format=fmt,
            input_id=data["inputId"],
            group=data["group"],
        )
        for fmt in stat_formats
    ]


# ── 호출 ────────────────────────────────────────────────────────────────────

_TOKEN_FIELDS = {
    "prompt": "prompt_token_count",
    "cached": "cached_content_token_count",
    "candidates": "candidates_token_count",
    "thoughts": "thoughts_token_count",
    "total": "total_token_count",
}


def install_replay_transport(client: GeminiLLMClient, capture: dict[str, Any]) -> None:
    """`client` 의 SDK 구조화 호출 직전에 요청 단위 타임아웃을 리플레이 값으로 덮고, 실제로 보낸 모델·타임아웃과 토큰을
    `capture` 에 담는다. 모델은 바꾸지 않는다 — 앱이 call_site 로 고른 값 그대로 나간다."""
    models = client._client.aio.models
    original = models.generate_content

    async def generate_content(**kwargs: Any) -> Any:
        config = kwargs.get("config") or genai_types.GenerateContentConfig()
        kwargs["config"] = config.model_copy(
            update={"http_options": genai_types.HttpOptions(timeout=REPLAY_TIMEOUT_MS)}
        )
        capture["sent_model"] = kwargs.get("model")
        capture["sent_timeout_ms"] = REPLAY_TIMEOUT_MS
        response = await original(**kwargs)
        usage = getattr(response, "usage_metadata", None)
        capture["tokens"] = {key: getattr(usage, attr, None) for key, attr in _TOKEN_FIELDS.items()}
        return response

    setattr(models, "generate_content", generate_content)  # noqa: B010 — 메서드 대입은 mypy 가 막는다


async def run_replay(
    client: LLMClient,
    capture: dict[str, Any],
    inputs: list[ReplayInput],
    *,
    reps: int,
    budget: CallBudget,
    room: ChatRoom | OfflineOwner,
    sink: Callable[[dict[str, Any]], None],
) -> None:
    for item in inputs:
        for rep in range(reps):
            if not budget.take():
                sink({"kind": "budgetExhausted", "limit": budget.limit, "input": item.kind, "rep": rep})
                return
            capture.clear()
            started = time.perf_counter()
            output: Any = None
            applied: list[dict[str, Any]] | None = None
            error: str | None = None
            try:
                parsed = await client.generate_structured(
                    item.prompt,
                    item.schema,
                    usage=LLMCallContext(call_site=item.call_site, user_id=room.user_id, room_id=room.id),
                )
                output = parsed.model_dump()
                if isinstance(parsed, StatJudgmentResult):
                    applied = stat_result(item, parsed)
            except Exception as exc:  # 기록하고 다음 호출로 — 실패도 결과다(컨텍스트 한도 등)
                error = f"{type(exc).__name__}: {str(exc)[:500]}"
            offline = {} if item.input_id is None else {"inputId": item.input_id, "group": item.group}
            sink(
                {
                    "kind": "call",
                    **offline,
                    "at": datetime.now(UTC).isoformat(),
                    "turn": item.turn,
                    "judgment": item.kind,
                    "variant": item.variant,
                    "statFormat": item.stat_format if item.kind == "stat" else None,
                    "endingId": str(item.ending_id) if item.ending_id else None,
                    "rep": rep,
                    "callSite": item.call_site,
                    "originalCallSite": item.original_call_site,
                    "sentModel": capture.get("sent_model"),
                    "sentTimeoutMs": capture.get("sent_timeout_ms"),
                    "tokens": capture.get("tokens"),
                    "latencyMs": round((time.perf_counter() - started) * 1000, 1),
                    "historyMessages": item.history_messages,
                    "promptChars": len(item.prompt),
                    "promptSha256": hashlib.sha256(item.prompt.encode()).hexdigest()[:16],
                    "output": output,
                    "statResult": applied,
                    "error": error,
                }
            )


def _prompt_sha(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def _offline_main(args: argparse.Namespace) -> int:
    """입력 파일을 조립해 프롬프트·plan 줄을 남기고, `--execute` 면 호출한다(파일 쓰기는 이벤트 루프 밖에서)."""
    prompt_set, sections = load_sections(Path(args.sections_json))
    per_file: list[tuple[dict[str, Any], list[ReplayInput]]] = []
    for path in args.input_json:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        per_file.append((data, build_offline_inputs(data, prompt_set, sections, args.stat_format or ["current"])))
    all_inputs = [item for _, items in per_file for item in items]
    models = check_same_models(all_inputs, settings.gemini_model_name)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.prompt_dir:
        Path(args.prompt_dir).mkdir(parents=True, exist_ok=True)
        for item in all_inputs:
            path = Path(args.prompt_dir) / f"{item.input_id}.{item.stat_format}.txt"
            path.write_text(item.prompt, encoding="utf-8")

    def sink(record: dict[str, Any]) -> None:
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    plans = []
    for data, items in per_file:
        plan = estimate(items, args.reps, models)
        plans.append(plan)
        sink(
            {
                "kind": "plan",
                "at": datetime.now(UTC).isoformat(),
                "inputId": data["inputId"],
                "group": data["group"],
                "source": data["source"],
                "roomId": data["roomId"],
                "turn": data["turn"],
                "variant": "offline",
                "sectionsJson": str(args.sections_json),
                "execute": args.execute,
                "models": models,
                "timeoutMs": REPLAY_TIMEOUT_MS,
                "inputs": [
                    {
                        "statFormat": i.stat_format,
                        "promptChars": len(i.prompt),
                        "promptSha256": _prompt_sha(i.prompt),
                        "statStart": i.stat_start,
                    }
                    for i in items
                ],
                **plan,
            }
        )
    total = {
        "inputs": len(per_file),
        "calls": sum(p["calls"] for p in plans),
        "estimatedUsd": round(sum(p["estimatedUsd"] for p in plans), 4),
    }
    print(json.dumps(total, ensure_ascii=False))
    if not args.execute:
        print("시험 실행 — LLM 을 부르지 않았다(--execute 로 실행)")
        return 0
    if total["calls"] > args.limit_calls:
        print(f"예정 호출 {total['calls']} 가 --limit-calls {args.limit_calls} 를 넘는다 — 상한까지만 부른다")
    asyncio.run(_offline_execute(per_file, reps=args.reps, budget=CallBudget(args.limit_calls), sink=sink))
    return 0


async def _offline_execute(
    per_file: list[tuple[dict[str, Any], list[ReplayInput]]],
    *,
    reps: int,
    budget: CallBudget,
    sink: Callable[[dict[str, Any]], None],
) -> None:
    client = GeminiLLMClient()
    capture: dict[str, Any] = {}
    install_replay_transport(client, capture)
    for data, items in per_file:
        owner = OfflineOwner(id=uuid.UUID(data["roomId"]))
        await run_replay(client, capture, items, reps=reps, budget=budget, room=owner, sink=sink)


async def _main(args: argparse.Namespace) -> int:
    from api.db.session import async_session_factory

    room_id = uuid.UUID(args.room)
    endings = [uuid.UUID(e) for e in args.ending] if args.ending else None
    async with async_session_factory() as db:
        room = await db.get(ChatRoom, room_id)
        if room is None:
            print(f"방이 없다: {room_id}")
            return 1
        stat_start = (
            stat_start_from_trace(Path(args.stat_start_trace), room_id, args.turn) if args.stat_start_trace else None
        )
        inputs = await build_inputs(
            db,
            room_id,
            args.turn,
            kinds=args.kind,
            variant=args.variant,
            ending_ids=endings,
            stat_start=stat_start,
            stat_formats=args.stat_format,
        )
    models = check_same_models(inputs, settings.gemini_model_name)
    plan = estimate(inputs, args.reps, models)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.prompt_out:
        for item in inputs:
            suffix = item.kind if item.stat_format == "current" else f"{item.kind}-{item.stat_format}"
            with open(f"{args.prompt_out}.{suffix}.txt", "w", encoding="utf-8") as f:  # noqa: ASYNC230 — 한 번 쓰는 CLI
                f.write(item.prompt)

    def sink(record: dict[str, Any]) -> None:
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    sink(
        {
            "kind": "plan",
            "at": datetime.now(UTC).isoformat(),
            "roomId": str(room_id),
            "turn": args.turn,
            "variant": args.variant,
            "execute": args.execute,
            "models": models,
            "timeoutMs": REPLAY_TIMEOUT_MS,
            "inputs": [
                {
                    "judgment": i.kind,
                    "statFormat": i.stat_format if i.kind == "stat" else None,
                    "endingId": str(i.ending_id) if i.ending_id else None,
                    "historyMessages": i.history_messages,
                    "promptChars": len(i.prompt),
                    "promptSha256": hashlib.sha256(i.prompt.encode()).hexdigest()[:16],
                    "statStart": i.stat_start or None,
                }
                for i in inputs
            ],
            **plan,
        }
    )
    print(json.dumps(plan, ensure_ascii=False))
    if not args.execute:
        print("시험 실행 — LLM 을 부르지 않았다(--execute 로 실행)")
        return 0
    if plan["calls"] > args.limit_calls:
        print(f"예정 호출 {plan['calls']} 가 --limit-calls {args.limit_calls} 를 넘는다 — 상한까지만 부른다")
    client = GeminiLLMClient()
    capture: dict[str, Any] = {}
    install_replay_transport(client, capture)
    await run_replay(client, capture, inputs, reps=args.reps, budget=CallBudget(args.limit_calls), room=room, sink=sink)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", help="방 id(오프라인 입력이 아니면 필수)")
    ap.add_argument("--turn", type=int, help="방 턴 번호(N 번째 완결 턴, 오프라인 입력이 아니면 필수)")
    ap.add_argument("--kind", action="append", choices=["image", "ending", "stat"], help="오프라인 입력이 아니면 필수")
    ap.add_argument("--input-json", action="append", help="오프라인 스탯 판정 입력 파일(여럿 가능) — DB 를 읽지 않는다")
    ap.add_argument("--sections-json", help="오프라인 입력의 레인 섹션·라벨 파일(stat_judgment_sections·labels)")
    ap.add_argument("--prompt-dir", help="오프라인 입력의 프롬프트를 <디렉터리>/<inputId>.<갈래>.txt 로 저장")
    ap.add_argument("--stat-start-trace", help="스탯 판정 시작 값을 읽을 서버 trace(stat_outcome) 파일")
    ap.add_argument(
        "--stat-format",
        action="append",
        choices=list(STAT_FORMATS),
        help="스탯 판정 프롬프트 갈래(여럿 가능, 기본 current)",
    )
    ap.add_argument("--prompt-out", help="만든 프롬프트를 판정 종류별로 이 접두 경로에 저장(<접두>.<종류>.txt)")
    ap.add_argument("--ending", action="append", help="엔딩 entity_id(여럿 가능) — 없으면 그 턴에 차례인 엔딩 전부")
    ap.add_argument("--variant", choices=["full", "window", "window-asof"], default="full")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--limit-calls", type=int, required=True, help="실호출 하드 상한")
    ap.add_argument("--out", required=True)
    ap.add_argument("--execute", action="store_true", help="LLM 을 실제로 부른다(사용자 승인 뒤에만)")
    args = ap.parse_args(argv)
    if args.input_json:
        if not args.sections_json:
            ap.error("--input-json 에는 --sections-json 이 필요하다")
        if args.room or args.turn is not None or (args.kind and args.kind != ["stat"]):
            ap.error("--input-json 은 스탯 판정 전용이고 --room/--turn 과 함께 쓰지 않는다")
        return _offline_main(args)
    if not args.room or args.turn is None or not args.kind:
        ap.error("--room, --turn, --kind 가 필요하다(또는 --input-json)")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
