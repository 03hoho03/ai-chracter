"""필터 재계산 — 지식 범위 필터가 프로브 질문 턴에 사실 섹션 후보에서 무엇을 뺐는지 하네스가 다시 계산한다(결정론 공변량).

스키마를 늘리지 않는다. 턴 기록(`chat_turns.memory_facts`)은 실은 행 id 만 담고, 필터의 입력(커서 이하 사실 행 · 이번 사용자 메시지 ·
직전 응답 · 이름)은 모두 템플릿 DB 와 프로브 기록에 있다. 판정은 서버 함수를 그대로 부른다: 장면 인물 집합과 남길지 판정
(`memory_fact_section._knowledge_filter` — 직전 응답을 스캔 글로 만드는 것까지 서버와 같다), 후보는 키별 최신 행
(`memory_knowledge.latest_by_key` — 필터는 그 후보에 걸린다). 그래서 필터를 켠 갈래에서 턴 기록에 실린 행이 재계산의 "뺀 행"에
들어 있으면 재계산이 서버와 어긋난 것이다.

센 것: 후보 수, 뺀 비밀 행(아는 사람이 정해졌는데 아무도 장면에 없다), 남긴 비밀 행과 그 이유(장면에 나온 아는 사람). 아는 사람이
정해지지 않은 행은 필터가 늘 남기므로 세지 않는다. 이 값은 판정을 바꾸지 않는다 — 누출 판정 문항의 공변량으로만 싣는다."""

import uuid
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from api.chat.memory_fact_section import _knowledge_filter
from api.chat.memory_facts import fact_rows_statement, normalize_part
from api.chat.memory_knowledge import KnowledgeScope, latest_by_key, room_names, scene_people, user_names
from api.chat.memory_window import MessageKey
from api.chat.prompt_builder import PromptNames
from api.db.models import ChatMessage, ChatMessageRole
from api.db.models.chat import ChatMemoryFact


def recompute_turn(
    rows: Sequence[ChatMemoryFact],
    *,
    history: Sequence[ChatMessage],
    user_content: str,
    names: PromptNames,
    user_label: str,
) -> dict[str, Any]:
    """`rows` 는 그 턴 커서 이하 사실 행 전부(쓴 순서), `history` 는 그 턴 사용자 메시지 앞까지의 방 대화(오프닝 포함)."""
    candidates = [row for _, row in latest_by_key(rows)]
    users = user_names(names.persona_name, user_label)
    scene = scene_people(
        room_names(rows, (), users=users), (user_content, _previous_text(history, user_content, names))
    )
    keep = _knowledge_filter(rows, KnowledgeScope(user_label=user_label), history=history, user_content=user_content,
                             names=names)  # fmt: skip
    secret = [row for row in candidates if row.known_by]
    return {
        "scenePeople": sorted(scene),
        "candidates": len(candidates),
        "droppedSecret": [str(row.id) for row in secret if not keep(row)],
        "keptSecret": [
            {"factId": str(row.id), "knownInScene": [k for k in row.known_by or () if normalize_part(k) in scene]}
            for row in secret
            if keep(row)
        ],
    }


def _previous_text(history: Sequence[ChatMessage], user_content: str, names: PromptNames) -> str:
    from api.chat.keyword_notes import recent_scan_turns

    return recent_scan_turns(history, user_content, 0, names=names)[0].assistant_text


def probe_history(base: Sequence[ChatMessage], turns: Sequence[Mapping[str, Any]]) -> tuple[list[ChatMessage], str]:
    """프로브 질문 턴의 (기록, 사용자 메시지). 두 턴 프로브는 앞 턴(설정 턴·맥락 턴)의 사용자 문장과 응답을 템플릿 대화 뒤에 더한다
    — 질문 턴의 직전 응답은 그 앞 턴의 응답이다."""
    history = list(base)
    last = history[-1].created_at if history else None
    for index, turn in enumerate(turns[:-1]):
        for offset, (role, content) in enumerate(
            ((ChatMessageRole.USER, str(turn["user"])), (ChatMessageRole.ASSISTANT, str(turn["reply"])))
        ):
            at = None if last is None else last + timedelta(seconds=2 * index + offset + 1)
            history.append(ChatMessage(id=uuid.uuid4(), role=role, content=content, created_at=at))
    return history, str(turns[-1]["user"])


def compare_recorded(
    result: Mapping[str, Any], recorded: Sequence[Mapping[str, Any]] | None, *, filter_on: bool
) -> dict[str, Any]:
    """턴 기록의 실은 행과 재계산을 견준다. 기록이 없으면(필터·사실 주입이 꺼진 갈래, 옛 프로브) 판정하지 않는다(None)."""
    if recorded is None:
        return {"recordedFactIds": None, "recordedDropped": [], "consistent": None}
    ids = [str(r["factId"]) for r in recorded]
    dropped = [i for i in ids if i in set(result["droppedSecret"])]
    return {"recordedFactIds": ids, "recordedDropped": dropped, "consistent": not (filter_on and dropped)}


async def recompute_probe(
    db: Any,
    room_id: uuid.UUID,
    *,
    cursor: MessageKey,
    turns: Sequence[Mapping[str, Any]],
    names: PromptNames,
    user_label: str,
) -> dict[str, Any]:
    """템플릿 DB(`db`, 프로브를 보낸 체크포인트 그대로)에서 그 프로브 질문 턴을 다시 계산한다."""
    from sqlalchemy import select

    rows = list((await db.scalars(fact_rows_statement(room_id, cursor))).all())
    base = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room_id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            )
        ).all()
    )
    history, question = probe_history(base, turns)
    return recompute_turn(rows, history=history, user_content=question, names=names, user_label=user_label)
