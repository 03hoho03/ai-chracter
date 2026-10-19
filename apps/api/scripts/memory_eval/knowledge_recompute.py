"""필터 재계산 — 지식 범위 필터가 프로브 질문 턴에 사실 섹션 후보에서 무엇을 뺐는지 하네스가 다시 계산한다(결정론 공변량).

스키마를 늘리지 않는다. 턴 기록(`chat_turns.memory_facts`)은 실은 행 id 만 담고, 필터의 입력(커서 이하 사실 행 · 이번 사용자 메시지 ·
직전 응답 · 이름)은 모두 템플릿 DB 와 프로브 기록에 있다. 판정은 서버 함수를 그대로 부른다: 장면 인물 집합과 남길지 판정
(`memory_fact_section._knowledge_filter` — 직전 응답을 스캔 글로 만드는 것까지 서버와 같다), 후보는 키별 최신 행
(`memory_knowledge.latest_by_key` — 필터는 그 후보에 걸린다). 그래서 필터를 켠 갈래에서 턴 기록에 실린 행이 재계산의 "뺀 행"에
들어 있으면 재계산이 서버와 어긋난 것이다.

센 것: 후보 수, 뺀 비밀 행(아는 사람이 정해졌는데 아무도 장면에 없다), 남긴 비밀 행과 그 이유(장면에 나온 아는 사람). 아는 사람이
정해지지 않은 행은 필터가 늘 남기므로 세지 않는다. 이 값은 판정을 바꾸지 않는다 — 누출 판정 문항의 공변량으로만 싣는다.

같은 입력으로 회상의 장면 가림 수와 따옴표 안 이름 재분류 수도 다시 센다(`recompute_ran`) — 판정·집계 입구가 그 장치가 측정
중에 실제로 일했는지 단언하는 입력이다(`memory_eval.ran_gate`)."""

import uuid
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from api.chat.memory_fact_section import _knowledge_filter
from api.chat.memory_facts import fact_rows_statement, normalize_part
from api.chat.memory_knowledge import KnowledgeScope, latest_by_key, scene_for_turn
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
    ignore_quoted_reply_names: bool,
) -> dict[str, Any]:
    """`rows` 는 그 턴 커서 이하 사실 행 전부(쓴 순서), `history` 는 그 턴 사용자 메시지 앞까지의 방 대화(오프닝 포함).
    `ignore_quoted_reply_names` 는 측정 서버가 그 턴에 넘긴 값과 같아야 한다(`ignores_quoted_reply_names`) — 서버는 지식 범위
    필터를 켠 턴에 직전 응답의 대사 따옴표 안에만 나온 이름을 장면 인물로 세지 않으므로, 다른 값으로 다시 계산하면 장면 인물과
    뺀 행이 서버와 조용히 어긋난다."""
    candidates = [row for _, row in latest_by_key(rows)]
    scope = KnowledgeScope(user_label=user_label, ignore_quoted_reply_names=ignore_quoted_reply_names)
    scene = scene_for_turn(rows, scope, history=history, user_content=user_content, names=names)
    keep = _knowledge_filter(rows, scope, history=history, user_content=user_content, names=names)
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


def ignores_quoted_reply_names(arm_overrides: Mapping[str, Any]) -> bool:
    """측정 서버가 그 갈래의 턴에 장면 인물을 셀 때 넘기는 값 — 서버는 지식 범위 필터 스위치를 켠 턴에 켠다(사실 주입이 꺼져
    있어도 회상의 가림이 같은 장면 인물을 쓴다). 측정 방은 기억 사용 범위 안(Opus)이라 범위 판정은 늘 참이다."""
    return bool(arm_overrides.get("memory_knowledge_filter"))


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
    ignore_quoted_reply_names: bool,
) -> dict[str, Any]:
    """템플릿 DB(`db`, 프로브를 보낸 체크포인트 그대로)에서 그 프로브 질문 턴을 다시 계산한다."""
    rows = list((await db.scalars(fact_rows_statement(room_id, cursor))).all())
    history, question = probe_history(await room_history(db, room_id), turns)
    return recompute_turn(
        rows,
        history=history,
        user_content=question,
        names=names,
        user_label=user_label,
        ignore_quoted_reply_names=ignore_quoted_reply_names,
    )


async def room_history(db: Any, room_id: uuid.UUID) -> list[ChatMessage]:
    """템플릿 DB 의 방 대화 전부(오프닝 포함), 서버가 읽는 순서로."""
    from sqlalchemy import select

    return list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room_id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            )
        ).all()
    )


async def recompute_ran(
    db: Any,
    room_id: uuid.UUID,
    *,
    cursor: MessageKey,
    turns: Sequence[Mapping[str, Any]],
    names: PromptNames,
    user_label: str,
    arm_overrides: Mapping[str, Any],
) -> dict[str, Any]:
    """그 프로브 질문 턴에 지식 범위 장치가 실제로 일했는지 — 서버의 회상·사실 섹션 함수를 그 갈래 설정으로 그대로 불러 센다
    (템플릿 DB 읽기만).

    실행 조건을 하네스에 베껴 두지 않으려고 서버 함수 본문을 그대로 돌리고 안쪽 호출만 엿본다. 회상 스위치를 켠 갈래는
    `memory_recall._recall`, 사실 주입을 켠 갈래는 `memory_fact_section._facts` 를 부른다 — 후보 장면이 회상 하한 아래면 가림까지
    가지 않고, 아는 사람이 정해진 행이 없으면 장면 인물을 세지 않으며, 사실 섹션은 지식 범위 필터를 켜고 비밀 행이 있을 때만
    필터를 거는 조건이 모두 서버 코드 그대로 걸린다.

    가림: 회상이 그 턴 후보에서 뺀 비밀 장면(`_hidden_episodes` 의 반환). 재분류: 서버가 따옴표 안을 지우고 장면 인물을 센
    호출(`scene_for_turn` — 지식 범위 필터를 켠 턴만 지운다)마다, 지우지 않고 셌으면 장면 인물이었을 이름. 질의 벡터는 주지
    않는다 — 가림과 장면 인물은 벡터를 읽기 전에 정해진다. 엿보기는 모듈 속성을 이 호출 동안만 바꾸므로 같은 프로세스에서
    서버 조립과 동시에 돌리지 않는다(하네스 명령은 한 흐름으로 돈다)."""
    from dataclasses import replace
    from unittest import mock

    from api.chat import memory_fact_section, memory_knowledge, memory_recall

    recall_on = bool(arm_overrides.get("memory_episodes_recall"))
    facts_on = bool(arm_overrides.get("memory_facts_inject"))
    filter_on = ignores_quoted_reply_names(arm_overrides)
    hidden: set[str] = set()
    reclassified: set[str] = set()
    if recall_on or facts_on:
        history, question = probe_history(await room_history(db, room_id), turns)
        scope = KnowledgeScope(user_label=user_label, ignore_quoted_reply_names=filter_on)
        real_scene = memory_knowledge.scene_for_turn
        real_hidden = memory_recall._hidden_episodes

        def scene_spy(rows: Any, used: KnowledgeScope, **kwargs: Any) -> frozenset[str]:
            found = real_scene(rows, used, **kwargs)
            if used.ignore_quoted_reply_names:
                reclassified.update(real_scene(rows, replace(used, ignore_quoted_reply_names=False), **kwargs) - found)
            return found

        async def hidden_spy(*args: Any, **kwargs: Any) -> set[uuid.UUID]:
            ids = await real_hidden(*args, **kwargs)
            hidden.update(str(episode_id) for episode_id in ids)
            return ids

        with (
            mock.patch.object(memory_recall, "scene_for_turn", scene_spy),
            mock.patch.object(memory_fact_section, "scene_for_turn", scene_spy),
            mock.patch.object(memory_recall, "_hidden_episodes", hidden_spy),
        ):
            if recall_on:
                await memory_recall._recall(
                    db, room_id=room_id, cursor=cursor, history=history, window=history, user_content=question,
                    names=names, scope=scope, query_vector=None,
                )  # fmt: skip
            if facts_on:
                await memory_fact_section._facts(
                    db, room_id=room_id, cursor=cursor, history=history, user_content=question, names=names,
                    scope=scope, knowledge_filter=filter_on, query_vector=None,
                )  # fmt: skip
    return {
        "hiddenEpisodeIds": sorted(hidden),
        "hiddenEpisodes": len(hidden),
        "reclassifiedNames": sorted(reclassified),
        "reclassified": len(reclassified),
    }
