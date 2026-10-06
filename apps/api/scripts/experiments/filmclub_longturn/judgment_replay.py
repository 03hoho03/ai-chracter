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
    # 생성 리플레이 응답으로 스탯 판정: 그 턴 원 응답 대신 생성 리플레이 기록의 응답마다 한 입력을 만든다. 스탯 정의는
    # 외부 JSON 으로 덮을 수 있다(보완판 「상영회까지」 범위·설명 등). 줄 형식은 운영 main 과 같은 A 만 허용한다.
    ... --kind stat --stat-start-trace <측정>/trace.jsonl --assistant-from <run>/replay/gen-<묶음>.jsonl \\
        --assistant-variant supplement --stat-override <정의.json> [--stat-start-set 상영회까지=50] \\
        --stat-format A --limit-calls 20 --limit-usd 5 --ledger '<run>/replay/**/*.jsonl' ...

입력은 격리 DB 의 방이다. 턴 N 은 N 번째 (사용자 메시지, 바로 뒤 응답) 쌍이고, 판정 입력의 히스토리는 그 사용자 메시지
앞의 메시지 전부다(유실 턴의 사용자 메시지도 서버가 그랬듯 히스토리에 든다). 프롬프트는 서버의 판정 준비 함수를 그대로
불러 만든다 — 판정 윈도 설정만 이 프로세스 안에서 끄거나 켠다. `window` 는 방의 현재 요약을 쓰므로 방의 마지막 턴에만
허용한다. `window-asof` 는 칸 판정만, 아무 턴에나 쓴다 — 그 턴 사용자 메시지보다 먼저 만들어진 요약 스냅샷 중 커서가 가장 큰
것(그 턴 판정 때의 현재 요약)으로 서버와 같은 윈도를 씌운다. 요약은 턴이 끝난 뒤 접히므로 그 턴 판정 때 있던 스냅샷은
사용자 메시지보다 먼저 생긴 것뿐이다. 칸 판정은 요약 본문을 싣지 않아 커서만 있으면 된다. 엔딩은 그 턴에 판정할 차례(게이트·5턴 간격)인 엔딩만 만들고,
스탯 규칙은 보지 않는다 — 실제로 판정이 불린 엔딩을 `--ending` 으로 고른다. 스탯 판정 프롬프트는 서버와 같은
빌더·같은 스탯 정의 순서로 만들고 현재값만 trace 의 시작 값으로 넣는다. 결과마다 서버 적용 규칙(방향·폭·범위)을 거친
값도 함께 남긴다.

스탯 줄 형식: 이 브랜치의 서버 빌더는 측정 때 코드라 줄이 `statId→이름→설명→범위→현재값` 순서다. 운영 main 은 그 뒤
설명이 길면 다른 스탯의 현재값을 기준으로 읽는 오독 때문에 `statId→이름→현재값→범위→설명`(제약 꼬리는 줄 끝)으로 바꿨고,
그 순서가 여기의 `A` 형식과 같다. 그래서 생성 리플레이 응답을 판정할 때는 `A` 만 받는다 — 운영에 나갈 판정과 같은 조립이다.

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
from sqlalchemy import inspect as sa_inspect
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
from api.db.models.story import StatDef
from api.llm.client import LLMCallContext, LLMCallSite, LLMClient, structured_model
from api.llm.gemini import GeminiLLMClient
from api.llm.pricing import estimate_cost_usd

# 스크립트로 실행할 때도 `scripts/` 를 패키지 기준으로 둔다(pytest·mypy 와 같은 모듈 경로).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.filmclub_longturn.replay_budget import CallBudget, ledger_paths, sum_ledger

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
    # 판정한 응답의 출처 — None 이면 그 턴 원 응답, 아니면 생성 리플레이 기록(갈래·반복 번호).
    source: str | None = None


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


# 덮을 수 있는 스탯 정의 칸. 판정 줄과 서버 적용 규칙이 읽는 칸이다.
STAT_OVERRIDE_FIELDS = frozenset(
    {
        "description",
        "min_value",
        "max_value",
        "initial_value",
        "max_change_per_turn",
        "change_direction",
        "per_turn_delta",
    }
)


def load_stat_overrides(path: Path) -> dict[str, dict[str, Any]]:
    """스탯 이름 → 덮을 칸. 형식 `{"stats": {"상영회까지": {"max_value": 46, "description": "..."}}}`."""
    data = json.loads(path.read_text(encoding="utf-8"))["stats"]
    for name, fields in data.items():
        unknown = set(fields) - STAT_OVERRIDE_FIELDS
        if unknown:
            raise ValueError(f"{name}: 덮을 수 없는 칸 {sorted(unknown)}")
    return dict(data)


def override_stat_defs(stat_defs: list[StatDef], overrides: dict[str, dict[str, Any]]) -> list[StatDef]:
    """덮은 값을 담은 세션 밖 사본(원 행은 그대로). 없는 스탯 이름을 덮으려 하면 멈춘다."""
    names = {stat_def.name for stat_def in stat_defs}
    missing = set(overrides) - names
    if missing:
        raise ValueError(f"시작설정에 없는 스탯: {sorted(missing)}")
    keys = [attr.key for attr in sa_inspect(StatDef).column_attrs]
    copies = []
    for stat_def in stat_defs:
        values = {key: getattr(stat_def, key) for key in keys}
        values.update(overrides.get(stat_def.name, {}))
        copies.append(StatDef(**values))
    return copies


def replies_from_generation(path: Path, turn: int, variant: str) -> list[tuple[str, str]]:
    """생성 리플레이 기록에서 그 턴·그 갈래의 응답(출처 라벨, 본문). 오류·빈 응답은 뺀다."""
    found = [
        (f"gen:{record['variant']}:rep{record['rep']}", str(record["reply"]))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for record in [json.loads(line)]
        if record.get("kind") == "call"
        and record.get("turn") == turn
        and record.get("variant") == variant
        and not record.get("error")
        and record.get("reply")
    ]
    if not found:
        raise ValueError(f"생성 기록에 턴 {turn} {variant} 응답이 없다")
    return found


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
    assistant_messages: list[tuple[str, str]] | None = None,
    stat_overrides: dict[str, dict[str, Any]] | None = None,
) -> list[ReplayInput]:
    if assistant_messages is not None and kinds != ["stat"]:
        raise ValueError("생성 리플레이 응답은 스탯 판정(stat)에만 넣는다")
    if assistant_messages is not None and any(f != "A" for f in stat_formats or ["current"]):
        raise ValueError("생성 리플레이 응답 판정은 운영 main 과 같은 줄 형식(A)만 쓴다")
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
        if stat_overrides:
            stat_defs = override_stat_defs(stat_defs, stat_overrides)
        expected = {str(stat_def.entity_id) for stat_def in stat_defs}
        if stat_start is None or set(stat_start) != expected:
            raise ValueError("스탯 판정은 그 턴의 시작 값이 스탯마다 있어야 한다(DB 에는 지금 값만 있다)")
        site, original = REPLAY_SITES["stat"]
        answers: list[tuple[str | None, str]] = (
            [(None, assistant.content)] if assistant_messages is None else list(assistant_messages)
        )
        for source, answer in answers:
            server_prompt = build_stat_judgment_prompt(
                prompt_set=prompt_set,
                sections=sections,
                stat_defs=stat_defs,
                current_stats=stat_start,
                user_message=user.content,
                assistant_message=answer,
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
                        source=source,
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
    room: ChatRoom,
    sink: Callable[[dict[str, Any]], None],
) -> None:
    for item in inputs:
        for rep in range(reps):
            if not budget.take():
                sink({**budget.exhausted(), "turn": item.turn, "input": item.kind, "rep": rep})
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
            tokens = capture.get("tokens")
            record: dict[str, Any] = {
                "kind": "call",
                "at": datetime.now(UTC).isoformat(),
                "turn": item.turn,
                "judgment": item.kind,
                "source": item.source,
                "variant": item.variant,
                "statFormat": item.stat_format if item.kind == "stat" else None,
                "endingId": str(item.ending_id) if item.ending_id else None,
                "rep": rep,
                "callSite": item.call_site,
                "originalCallSite": item.original_call_site,
                "sentModel": capture.get("sent_model"),
                "sentTimeoutMs": capture.get("sent_timeout_ms"),
                "tokens": tokens,
                "costUsd": _cost(capture.get("sent_model"), tokens),
                "latencyMs": round((time.perf_counter() - started) * 1000, 1),
                "historyMessages": item.history_messages,
                "promptChars": len(item.prompt),
                "promptSha256": hashlib.sha256(item.prompt.encode()).hexdigest()[:16],
                "output": output,
                "statResult": applied,
                "error": error,
            }
            budget.charge(record)
            record["cumulativeChargedUsd"] = round(budget.spent_usd, 6)
            sink(record)


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
        overrides = load_stat_overrides(Path(args.stat_override)) if args.stat_override else None
        if args.stat_start_set:
            if stat_start is None:
                print("--stat-start-set 은 --stat-start-trace 의 시작 값 위에 덮는다")
                return 1
            setup = await _require_starting_setup(db, room)
            assert setup is not None
            ids = {d.name: str(d.entity_id) for d in (await _load_room_stats(db, room.id, setup.id))[0]}
            for item in args.stat_start_set:
                name, _, value = item.partition("=")
                stat_start[ids[name]] = float(value)
        replies = (
            replies_from_generation(Path(args.assistant_from), args.turn, args.assistant_variant)
            if args.assistant_from
            else None
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
            assistant_messages=replies,
            stat_overrides=overrides,
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
                    "source": i.source,
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
    spent = sum_ledger(ledger_paths(args.ledger)).charged_usd if args.ledger else 0.0
    if args.limit_usd is not None and spent >= args.limit_usd:
        print(f"장부 누적 ${spent:.4f} 가 이미 상한 ${args.limit_usd} 이상이다 — 부르지 않는다")
        return 3
    budget = CallBudget(args.limit_calls, usd_limit=args.limit_usd, spent_usd=spent)
    await run_replay(client, capture, inputs, reps=args.reps, budget=budget, room=room, sink=sink)
    print(json.dumps({"calls": budget.used, "cumulativeChargedUsd": round(budget.spent_usd, 6)}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", required=True)
    ap.add_argument("--turn", type=int, required=True, help="방 턴 번호(N 번째 완결 턴)")
    ap.add_argument("--kind", action="append", choices=["image", "ending", "stat"], required=True)
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
    ap.add_argument("--limit-usd", type=float, help="장부 포함 실제 원가 누적 상한(달러)")
    ap.add_argument("--ledger", help="앞 묶음 호출 기록 glob(재귀 **) — 실제 원가를 상한에 넣는다")
    ap.add_argument("--assistant-from", help="스탯 판정에 넣을 응답을 이 생성 리플레이 기록에서 읽는다")
    ap.add_argument("--assistant-variant", default="supplement", help="--assistant-from 에서 고를 갈래")
    ap.add_argument("--stat-override", help="스탯 정의를 덮는 JSON(스탯 이름 → 칸)")
    ap.add_argument("--stat-start-set", action="append", help="시작 값 덮기 NAME=VALUE(여럿 가능)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--execute", action="store_true", help="LLM 을 실제로 부른다(사용자 승인 뒤에만)")
    return asyncio.run(_main(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
