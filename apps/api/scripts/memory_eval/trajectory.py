"""턴당 생성 프롬프트 궤적 — 그 시점 DB 로 다음 턴의 생성 프롬프트를 실제 조립 함수(`build_room_prompt`)로 만들어 잰다. LLM 없음.

한 점 = (다음 턴 번호, 갈래): 전체 글자, 캐시 블록 셋의 길이와 앞 두 블록의 해시(갈래끼리 같아야 캐시가 유지된다), 섹션별
글자(기억 노트·요약·원문 윈도·회상·키워드북), 회상 결과, 방 메시지 전체 SELECT 시간. 같은 DB 상태에서 갈래마다 설정만 바꿔
조립한다. 토큰 수는 따로 켤 때만 Anthropic `count_tokens`(무료)로 센다 — 키가 없으면 켤 수 없다."""

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.keyword_notes import match_keyword_notes
from api.chat.memory_window import load_current_summary, prompt_window
from api.chat.turn_prompt import build_room_prompt
from api.core.config import settings
from api.db.models import ChatMessage
from api.db.models.story import KeywordNote
from api.llm.chat_models import ChatModelId
from api.llm.client import SegmentedPrompt

from memory_eval.attribution import recall_section
from memory_eval.runtime import arm_settings, load_room, story_generation_set

# 회상 섹션 머리글(생성 채널 문안의 첫 줄). 문안이 바뀌면 실행 인자로 준다.
DEFAULT_RECALL_HEADER = "[지난 기억 — 참고]"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


async def assemble_point(
    db: AsyncSession,
    room_id: uuid.UUID,
    *,
    next_turn: int,
    user_content: str,
    arm: str,
    model: ChatModelId,
    recall_header: str = DEFAULT_RECALL_HEADER,
    recall_field: str | None = None,
) -> tuple[dict[str, Any], str]:
    """다음 턴의 프롬프트를 조립해 한 점과 프롬프트 본문을 돌려준다."""
    ctx = await load_room(db, room_id)
    started = time.perf_counter()
    history = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room_id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            )
        ).all()
    )
    history_ms = (time.perf_counter() - started) * 1000
    prompt_set, sections = await story_generation_set(db, model)
    with arm_settings(arm):
        started = time.perf_counter()
        generation = await build_room_prompt(db, ctx.room, ctx.setup, history, user_content, None, prompt_set, sections)
        build_ms = (time.perf_counter() - started) * 1000
    prompt = generation.prompt
    summary = await load_current_summary(db, room_id) if settings.memory_window_generation else None
    window = (
        prompt_window(history, summary.cursor if summary else None) if settings.memory_window_generation else history
    )
    notes = (
        await db.scalars(
            select(KeywordNote)
            .where(
                KeywordNote.content_version_id == ctx.room.content_version_id,
                or_(KeywordNote.starting_setup_id.is_(None), KeywordNote.starting_setup_id == ctx.setup.id),
            )
            .order_by(KeywordNote.order, KeywordNote.entity_id)
        )
    ).all()
    matched = match_keyword_notes(notes, window, user_content, names=ctx.names)
    segments = prompt.segments if isinstance(prompt, SegmentedPrompt) else (prompt,)
    recall = recall_section(prompt, recall_header)
    recalled = recall_result(generation, field=recall_field, arm=arm)
    check_recall_section(recalled, section=recall)
    point = {
        "turn": next_turn,
        "arm": arm,
        "chars": len(prompt),
        "segmentChars": [len(s) for s in segments],
        "segmentSha": [_sha(s) for s in segments[:2]],
        "noteChars": len(ctx.room.memory_note) if ctx.room.memory_note and ctx.room.memory_note in prompt else 0,
        "summaryChars": len(summary.text) if summary and summary.text in prompt else 0,
        "windowMessages": len(window),
        "windowChars": sum(len(m.content) for m in window),
        "keywordNotes": len(matched),
        "keywordNoteChars": sum(len(n.info_text) for n in matched if n.info_text in prompt),
        "recallChars": len(recall),
        "recall": recalled,
        "historyMessages": len(history),
        "historySelectMs": round(history_ms, 3),
        "buildMs": round(build_ms, 3),
    }
    return point, str(prompt)


async def count_tokens(prompt: str, system: str, *, model: str = "claude-opus-5-5") -> int:
    """Anthropic 토큰 세기(무료). 키가 비었으면 호출하지 않고 거부한다."""
    if not settings.anthropic_direct_api_key:
        raise SystemExit("토큰 세기는 Anthropic 키가 있어야 한다(무료지만 대화 글이 Anthropic 으로 간다) — 켜지 않았다")
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_direct_api_key)
    messages: Any = [{"role": "user", "content": prompt}]
    result = (
        await client.messages.count_tokens(model=model, system=system, messages=messages)
        if system
        else await client.messages.count_tokens(model=model, messages=messages)
    )
    return int(result.input_tokens)


def append_point(path: Path, point: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(point, ensure_ascii=False) + "\n")


# 회상을 켜는 갈래. 이 갈래는 조립 결과에 회상 칸이 있어야 한다.
RECALL_ARMS = frozenset({"B"})


def recall_result(generation: Any, *, field: str | None, arm: str) -> list[Any] | None:
    """조립 결과의 회상 칸(이름은 실행 인자로 받는다 — 추측하지 않는다). 칸이 없으면 None("칸 없음"), 있으면 그 목록(빈
    목록 = "회상 없음"). 회상 갈래에서 칸이 없으면 회상을 구현하지 않은 코드이므로 거부한다."""
    fields = generation._asdict() if hasattr(generation, "_asdict") else {}
    if field is None or field not in fields:
        if arm in RECALL_ARMS:
            raise SystemExit(
                f"갈래 {arm} 인데 조립 결과에 회상 칸({field!r})이 없다 — 칸 이름을 --recall-field 로 준다"
            )
        return None
    return list(fields[field])


def check_recall_section(result: list[Any] | None, *, section: str) -> None:
    """회상이 실린 턴인데 프롬프트에서 머리글을 찾지 못하면 섹션 글자 수를 0 으로 잘못 세게 된다 — 거부한다."""
    if result and not section:
        raise SystemExit("회상이 실렸는데 프롬프트에서 회상 머리글을 찾지 못했다 — --recall-header 확인")
