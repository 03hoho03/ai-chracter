"""오프라인 시제품 추출 — 체크포인트 덤프를 복원한 DB 의 스냅샷마다 접힌 창을 만들어 초안 지시문으로 Haiku 5.5 를 직접
부르고(사고 끔·effort low) 결과를 JSON 으로 저장한다(DB 에 넣지 않는다). 구현 전에 추출 문안과 명사 방식을 재는 용도다.

창 = (직전 스냅샷 커서, 이 스냅샷 커서]. 직전이 없으면 방의 처음부터(오프닝 제외). 줄은 `[i] 라벨: 글`(i 는 1부터), 라벨은
요약 입력과 같고 글은 미디어 태그를 지운다(태그 속 칸 id·조각이 명사로 새지 않게). 앞 창의 마지막 장면 제목 2개를 이어 쓰기용
입력으로 준다. 모델이 돌려준 줄 번호는 서버가 1~n 으로 맞추고 뒤집혔으면 바꾼 뒤 턴 순번으로 옮긴다: 시작 턴 = 1 + 그 메시지
앞의 오프닝 아닌 진행자 메시지 수, 끝 턴 = 그 메시지까지의 수.

지시문은 파일로 받는다(개발 절반으로 고치는 판마다 원장에 남는다). 기본은 드라이런 — 창 수·입력 글자·견적만 낸다."""

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import opening_message
from api.chat.prompt_builder import PromptNames, _turn_text
from api.db.models import ChatMessage, ChatMessageRole, ChatRoomMemorySnapshot
from api.db.models.prompt import PromptSet

from memory_eval.ledger import Ledger

EXTRACT_MODEL = "claude-haiku-5-5"
# 창 하나 견적: 입력 약 4K 토큰 × 토크나이저 1.3, 출력 약 1.5K.
EXTRACT_CALL_ESTIMATE_USD = 0.002
# 서버 절단 상한 — 저장 전에 서버가 자르는 길이와 장면 수(운영 스키마의 같은 상수와 맞춘다).
MAX_EPISODES = 10
TITLE_MAX = 60
DETAIL_MAX = 300
_SENTENCE_ENDS = (".", "다", "요")


class PrototypeEpisode(BaseModel):
    title: str
    detail: str
    nouns: list[str]
    keywords: list[str]
    asserted_by: Literal["user", "character", "narration", "mixed"]
    evidence: list[str]
    importance: int
    start_line: int
    end_line: int


class PrototypeResult(BaseModel):
    episodes: list[PrototypeEpisode]


@dataclass(frozen=True)
class Window:
    snapshot_id: uuid.UUID
    messages: list[ChatMessage]
    turn_before: int  # 창 앞의 오프닝 아닌 진행자 메시지 수
    fold_turn: int  # 이 스냅샷이 접힌 턴 = 스냅샷 생성 시각까지 들어온 진행자 메시지 수


def line_turns(window: Window) -> list[int]:
    """창의 줄마다 턴 순번(그 줄까지 진행자 메시지가 몇 개였나 + 1, 진행자 줄은 자기 자신 포함)."""
    turns = []
    count = window.turn_before
    for message in window.messages:
        if message.role == ChatMessageRole.ASSISTANT:
            count += 1
            turns.append(count)
        else:
            turns.append(count + 1)
    return turns


def map_lines(window: Window, start_line: int, end_line: int) -> tuple[int, int]:
    n = len(window.messages)
    start = min(max(start_line, 1), n)
    end = min(max(end_line, 1), n)
    if start > end:
        start, end = end, start
    turns = line_turns(window)
    return turns[start - 1], turns[end - 1]


async def build_windows(db: AsyncSession, room_id: uuid.UUID) -> list[Window]:
    messages = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room_id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            )
        ).all()
    )
    opening = opening_message(messages)
    body = [m for m in messages if m is not opening]
    snapshots = (
        await db.scalars(
            select(ChatRoomMemorySnapshot)
            .where(ChatRoomMemorySnapshot.chat_room_id == room_id)
            .order_by(ChatRoomMemorySnapshot.cursor_created_at, ChatRoomMemorySnapshot.cursor_message_id)
        )
    ).all()
    windows: list[Window] = []
    previous: tuple[Any, uuid.UUID] | None = None
    for snapshot in snapshots:
        cursor = (snapshot.cursor_created_at, snapshot.cursor_message_id)
        inside = [
            m for m in body if (previous is None or (m.created_at, m.id) > previous) and (m.created_at, m.id) <= cursor
        ]
        before = sum(
            1
            for m in body
            if m.role == ChatMessageRole.ASSISTANT and previous is not None and (m.created_at, m.id) <= previous
        )
        folded_at = sum(1 for m in body if m.role == ChatMessageRole.ASSISTANT and m.created_at <= snapshot.created_at)
        windows.append(Window(snapshot_id=snapshot.id, messages=inside, turn_before=before, fold_turn=folded_at))
        previous = cursor
    return windows


def render_window(window: Window, prompt_set: PromptSet, names: PromptNames) -> str:
    lines = []
    for i, message in enumerate(window.messages, start=1):
        label = prompt_set.user_label if message.role == ChatMessageRole.USER else prompt_set.story_assistant_label
        lines.append(f"[{i}] {label}: {_turn_text(message, names, strip_tags=True)}")
    return "\n".join(lines)


def build_prompt(instruction: str, user_name: str, previous_titles: list[str], turn_lines: str) -> str:
    parts = [instruction.strip(), f"사용자의 이야기 속 이름: {user_name}"]
    if previous_titles:
        parts.append("[앞 구간의 마지막 장면]\n" + "\n".join(previous_titles))
    parts.append("[접힌 대화]\n" + turn_lines)
    return "\n\n".join(parts)


async def call_haiku(api_key: str, prompt: str, ledger: Ledger, *, stage: str) -> PrototypeResult:
    if not api_key:
        raise SystemExit("시제품 추출은 Anthropic 키가 있어야 한다")
    import anthropic

    from api.llm.claude_messages import message_usage, parse_structured, structured_output_config

    ledger.check_headroom(EXTRACT_CALL_ESTIMATE_USD)
    output_config: Any = {**structured_output_config(PrototypeResult), "effort": "low"}
    message = await anthropic.AsyncAnthropic(api_key=api_key).messages.create(
        model=EXTRACT_MODEL,
        max_tokens=8_000,
        thinking={"type": "disabled"},
        output_config=output_config,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = message_usage(message)
    ledger.append(
        stage=stage,
        call_site="memory_eval_prototype_extract",
        model=EXTRACT_MODEL,
        input_tokens=usage.prompt_token_count,
        cached_tokens=usage.cached_content_token_count,
        cache_write_tokens=usage.cache_write_token_count,
        output_tokens=usage.candidates_token_count,
        thoughts_tokens=usage.thoughts_token_count,
    )
    return parse_structured(message, PrototypeResult, "anthropic", "Anthropic")


def truncate_detail(detail: str, limit: int = DETAIL_MAX) -> str:
    """상한을 넘으면 상한 안의 마지막 문장 끝(`.`·`다`·`요`) 뒤에서, 없으면 글자 단위로 자른다."""
    if len(detail) <= limit:
        return detail
    head = detail[:limit]
    cut = max(head.rfind(mark) for mark in _SENTENCE_ENDS)
    return head[: cut + 1] if cut >= 0 else head


def episode_rows(window: Window, result: PrototypeResult, *, version: str) -> list[dict[str, Any]]:
    """오프라인 회상 입력 꼴(`recall_offline.load_episodes_json`). 서버가 저장 전에 하는 것처럼 빈 본문을 버린 뒤 앞에서부터
    10개, 제목·본문을 상한에서 자른다(빈 장면이 자리를 먹어 뒤쪽 장면이 잘리지 않게 빈 것을 먼저 버린다). 명사 정규화는 시제품
    검색 쪽에서 한다."""
    kept = [e for e in result.episodes if e.detail.strip()][:MAX_EPISODES]
    rows = []
    for k, episode in enumerate(kept):
        start, end = map_lines(window, episode.start_line, episode.end_line)
        detail = episode.detail.strip()
        rows.append(
            {
                "id": f"{window.snapshot_id}:{k}",
                "snapshot_id": str(window.snapshot_id),
                "start_turn": start,
                "end_turn": end,
                "title": episode.title.strip()[:TITLE_MAX],
                "detail": truncate_detail(detail),
                "truncated": len(detail) > DETAIL_MAX,
                "rawCount": len(result.episodes),
                "rawEmpty": sum(1 for e in result.episodes if not e.detail.strip()),
                "nouns": episode.nouns,
                "keywords": episode.keywords,
                "asserted_by": episode.asserted_by,
                "evidence": episode.evidence,
                "importance": min(max(episode.importance, 1), 5),
                "available_from_turn": window.fold_turn + 1,
                "promptVersion": version,
            }
        )
    return rows


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
