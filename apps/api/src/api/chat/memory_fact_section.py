"""매 턴 사실 섹션 — 방의 관계·사실 기억(`chat_memory_facts`)을 키마다 지금 값으로 줄이고, 상시 몫과 이번 턴 사용자 메시지에
관련된 행을 글자 상한 안에서 골라 생성 프롬프트의 사실 섹션(대화 기록 뒤, 회상 앞)에 싣는다. LLM 을 부르지 않는다(DB 읽기 한
번과 파이썬 계산).

읽는 행: 그 턴 요약 커서 이하에서 접힌 스냅샷의 행 전부를 쓴 순서(스냅샷 커서 순, 그 안은 순번 순)로. 커서 뒤는 원문 윈도우로
이미 실리고, 지난 턴을 그때의 커서로 다시 조립하면 그 뒤에 접힌 스냅샷의 행은 그때 없던 사실이다. 되감기는 스냅샷을 지우고
DB 가 그 행을 함께 지우므로 다음 읽기에 앞 값이 돌아온다.

키별 최신(`chat/memory_knowledge.py` 의 `latest_by_key`): 같은 키의 마지막 행이 이기되, 같은 키에 같은 값의 반증 행이 앞에
있으면 그 반증 행이 이긴다(규칙은 그 모듈 설명).

렌더 순서: 관계 → 아는 사람이 정해진 사실 → 반증 → 그 밖. 묶음 안은 중요도가 높은 쪽, 같으면 나중에 쓴 쪽이 먼저다.

고르기(줄 비용 = 줄 글자 수 + 첫 줄 뒤마다 줄바꿈 1): 렌더 순서 전부가 상한 안이면 전부. 아니면 ① 렌더 순서로 상한의
`CONSTANT_RATIO` 까지(다음 줄이 넘으면 멈춤) ② 이름 정확 조회 — 장면 인물이 주어거나 관계 대상인 행을 렌더 순서로 상한의
`CONSTANT_RATIO + EXACT_RATIO` 까지(다음 줄이 넘으면 멈춤) ③ 이번 턴 사용자 메시지와 명사가 겹치고 점수가 `RELEVANCE_TAU` 이상인
행을 순위대로 상한까지(다음 줄이 넘으면 멈춤) ④ 남은 자리를 ①이 멈춘 곳부터 렌더 순서로 다시 채운다(다음 줄이 넘으면 멈추고
뒤의 짧은 줄로 건너뛰지 않는다). 실린 행은 렌더 순서로 쓴다. 몫의 끝은 모두 섹션 첫 줄부터 센 누적 글자다. 관련 점수는 장면
회상의 토큰·점수 함수를 그대로 쓴다(행 명사 = 주어·대상이나 속성·값의 조사 뗀 토큰, 질의에서 이름·불용어·방 행의 20% 넘게 나오는
명사를 뺀다, 행 5개 미만이면 관련 행 없음).

이름 정확 조회: 관련 점수는 이름으로 찾지 못한다 — 질의에서 작품·사용자 이름을 빼고, 주인공처럼 여러 행의 주어인 이름은 흔한
명사로 빠지며, 질의는 이번 사용자 메시지뿐이라 직전 응답에만 나온 인물은 보지 않는다. 그래서 "이 인물에 대해" 묻는 턴에 그 인물의
행이 상시 몫 밖이면 실리지 않았다. 장면 인물은 지식 범위 필터와 같은 함수로 센다(방 사실 행의 이름 중 이번 사용자 메시지나 직전
응답에 나오는 것, 사용자 제외) — 필터를 끈 턴에도 센다. 값·속성에 이름이 들어 있을 뿐인 행은 걸지 않는다. 정확 조회는 필터를
지난 행 사이에서만 고르므로, 이름이 나와도 아는 사람이 장면에 없는 비밀 행은 돌아오지 않는다. 몫의 끝을 상한 전부가 아니라
상시 몫 끝 + 상시 몫 크기로 두어, 주인공 이름이 직전 응답에 늘 나오는 방에서도 관련 몫이 들어갈 자리(상한의
1 − `CONSTANT_RATIO` − `EXACT_RATIO`)가 남는다.

임베딩 회상(`memory_embed_recall`, `chat/memory_vector.py`)이 켜져 질의 벡터가 오면 ③의 순서는 명사 순위와, 키별 최신이고
필터를 지난 행 중 질의와 가까운 순(거리 상한 안)의 RRF 다 — 명사가 겹치지 않는 바꿔 말하기도 관련 몫에 든다. 거리 순위를 필터 뒤
행 사이에서만 매기므로 필터가 뺀 비밀 행은 거리가 가까워도 돌아오지 않는다. 가까운 행이 없으면 ③은 명사 단독 그대로다.

확인되지 않은 주장: 키별 최신 행이 `claimed` 이고 사용자 꼬리표가 붙지 않는 행(인물·서술이 말로만 전한 것)이면 고르기 전에
뺀다(`unverified_claim`) — 꼬리표를 붙여도 생성 모델이 사실로 굳힌다. 키별 최신 뒤에서 빼므로 그 키는 이번 턴 통째로 빠지고 옛
값이 되살아나지 않는다. 지식 범위 필터와 별도 판정이라 필터가 꺼져 있어도 걸리고, 네 몫(상시·정확 조회·관련·임베딩) 모두 뺀 뒤의
행에서 고른다. 확인된 행·반증 행·사용자 주장은 싣는다. 리플레이는 기록한 행을 그대로 렌더한다.

지식 범위 필터(`chat/memory_knowledge.py`, 호출부가 켰을 때만): 키별 최신 행 중 아는 사람이 이번 장면에 없는 행을 고르기
전에 뺀다 — 빠진 자리는 다음 후보가 채우고, 같은 키의 앞 값이 지금 값처럼 되살아나지 않는다. 이름 출처는 읽은 사실 행뿐이라
SQL 을 더하지 않는다. 판정은 아는 사람 원소가 장면에 나오는가뿐이고 그 원소는 이미 사실 행에서 이름 출처에 들어 있어, 미디어 북
인물이나 작품 이름을 더해도 판정이 바뀌지 않는다(더 읽으면 그 읽기의 실패로 섹션이 통째로 빠질 자리만 는다).

상수와 고르기는 평가 하네스의 시제품을 개발 절반 격자로 맞춘 값과 절차다. 줄 모양만 하네스와 다르다 — 운영 섹션 문안이 설명하는
꼬리표를 쓴다.

읽기는 요청 세션의 SAVEPOINT 안이고, DB 오류든 그 밖의 예외든 경고·승격을 남기고 섹션 없이 조립한다(생성 프롬프트 조립은 SSE
제너레이터 본문 안이라 예외가 새면 무관한 요청까지 500 이 된다)."""

import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import memory_recall
from api.chat.memory_facts import fact_rows_statement, normalize_part
from api.chat.memory_knowledge import KnowledgeScope, known_in_scene, latest_by_key, scene_for_turn
from api.chat.memory_nouns import rule_tokens
from api.chat.memory_recall import RecallCandidate, query_tokens, score_episodes
from api.chat.memory_vector import QueryVector, fact_distances, rrf_order
from api.chat.memory_window import MessageKey, opening_message
from api.chat.prompt_builder import PromptNames
from api.core.config import settings
from api.core.sentry import capture_dependency_failure
from api.db.models.chat import ChatMemoryFact, ChatMessage, ChatMessageRole

logger = logging.getLogger(__name__)

# 사실 줄을 이어 붙인 글의 상한(줄바꿈 포함 글자 수), 그중 렌더 순서로만 채우는 상시 몫, 그 뒤 장면 인물의 행으로 채우는 정확
# 조회 몫(상시 몫과 같은 크기 — 상한 비율이고 몫의 끝은 둘을 더한 누적), 관련 행의 점수 임계.
RENDER_MAX_CHARS = 700
CONSTANT_RATIO = 0.3
EXACT_RATIO = 0.3
RELEVANCE_TAU = 0.6
# 뒤집힌 사실의 줄 앞 표지. 뜻은 사실 섹션 문안이 설명한다.
DISPROVED_MARK = "(사실 아님으로 밝혀짐) "


@dataclass(frozen=True)
class FactSection:
    """이번 턴의 사실 섹션 — 섹션에 실을 줄(없으면 `""`)과 턴 기록 칸에 남길 목록 `[{factId, chars}]`(줄 순서)."""

    lines: str
    record: tuple[dict[str, Any], ...]


NO_FACTS = FactSection("", ())


class FactRecordMissingError(Exception):
    """턴 기록에 남은 사실이 지금 DB 에 없다(그 뒤 되감기로 지워졌다)."""


def fact_body(row: ChatMemoryFact) -> str:
    """사실 한 줄의 꼬리표 없는 본문 — 관계면 `주어 → 대상: 값`, 속성이면 `주어 · 속성: 값`. 임베딩 채우기도 이 글을 임베딩한다."""
    if row.kind == "relation":
        return f"{row.subject} → {row.object}: {row.value}"
    return f"{row.subject} · {row.attribute}: {row.value}"


def fact_line(row: ChatMemoryFact, *, user_name: str | None = None) -> str:
    """사실 한 줄. 꼬리표는 이 순서로 붙는다 — 반증이면 줄 앞 표지, 주장이면 끝에 말한 쪽, 아는 사람이 있으면 그 뒤에
    `(이름·이름만 앎)`. 말한 쪽은 사용자가 내놓은 주장이거나 말한 사람이 그 턴 사용자의 이야기 속 이름(`user_name`, 사실 키와
    같은 정규화로 견준다)이면 사용자 꼬리표다 — 추출이 사용자 말을 그 이름의 인물 말로 적어도 사용자가 한 말로 읽히게. 그 밖은
    말한 인물 이름, 이름이 없으면 인물 꼬리표다. 사용자·인물 꼬리표는 회상 줄과 같은 상수다(두 섹션 문안이 같은 꼬리표를
    설명한다)."""
    line = fact_body(row)
    if row.truth_status == "disproved":
        line = DISPROVED_MARK + line
    elif row.truth_status == "claimed":
        if _claimed_by_user(row, user_name):
            line += memory_recall.USER_ASSERTION_TAIL
        elif row.speaker:
            line += f" ({row.speaker}의 말)"
        else:
            line += memory_recall.CHARACTER_ASSERTION_TAIL
    if row.known_by:
        line += f" ({'·'.join(row.known_by)}만 앎)"
    return f"- {line}"


def _claimed_by_user(row: ChatMemoryFact, user_name: str | None) -> bool:
    """주장의 말한 쪽이 사용자인가 — 사용자가 내놓은 주장이거나 말한 사람이 사용자의 이야기 속 이름(정규형)이다."""
    spoken_by_user = bool(user_name and row.speaker and normalize_part(row.speaker) == normalize_part(user_name))
    return row.asserted_by == "user" or spoken_by_user


def unverified_claim(row: ChatMemoryFact, *, user_name: str | None) -> bool:
    """섹션에 싣지 않는 행인가 — 확인되지 않은 주장이고 사용자 꼬리표가 붙지 않는다(인물·서술이 말로만 전한 것). 꼬리표를
    붙여도 생성 모델이 사실로 굳혀 싣지 않는다. 확인된 행·반증 행·사용자 주장은 싣는다."""
    return row.truth_status == "claimed" and not _claimed_by_user(row, user_name)


def _group(row: ChatMemoryFact) -> int:
    if row.kind == "relation":
        return 0
    if row.known_by:
        return 1
    if row.truth_status == "disproved":
        return 2
    return 3


def _relevant(ordered: Sequence[ChatMemoryFact], query: str, names: Sequence[str], current_turn: int) -> list[int]:
    """`ordered`(렌더 순서의 키별 최신 행) 가운데 `query` 와 명사가 겹치고 점수가 임계 이상인 행의 위치, 순위 순."""
    nouns = [
        frozenset(rule_tokens(f"{row.subject} {row.object or row.attribute or ''} {row.value}")) for row in ordered
    ]
    candidates = [
        RecallCandidate(id=str(i), nouns=nouns[i], importance=row.importance, end_turn=row.end_turn, snapshot=0)
        for i, row in enumerate(ordered)
    ]
    pool = frozenset(noun for row_nouns in nouns for noun in row_nouns)
    tokens = query_tokens(query, "", episode_nouns=pool, names=names)
    scored = score_episodes(candidates, tokens, current_turn=current_turn)
    return [int(x.id) for x in scored if x.overlap and x.s >= RELEVANCE_TAU]


def _named(row: ChatMemoryFact, scene: frozenset[str]) -> bool:
    """주어나 관계 대상이 장면 인물(정규형)인가. 사실의 속성·값은 이름 자리가 아니다."""
    if normalize_part(row.subject) in scene:
        return True
    return row.kind == "relation" and normalize_part(row.object) in scene


def _nearest(ordered: Sequence[ChatMemoryFact], distances: Mapping[uuid.UUID, float]) -> list[int]:
    """`ordered` 가운데 거리가 있는 행의 위치, 가까운 순(같으면 렌더 순서)."""
    near = [i for i, row in enumerate(ordered) if row.id in distances]
    return sorted(near, key=lambda i: (distances[ordered[i].id], i))


def select_fact_rows(
    rows: Sequence[ChatMemoryFact],
    *,
    query: str,
    names: Sequence[str],
    current_turn: int,
    user_name: str | None = None,
    keep: Callable[[ChatMemoryFact], bool] | None = None,
    distances: Mapping[uuid.UUID, float] | None = None,
    rrf_k: int = 60,
    scene: frozenset[str] = frozenset(),
) -> list[ChatMemoryFact]:
    """쓴 순서의 행 전부에서 섹션에 실을 행을 렌더 순서로 고른다(규칙은 모듈 설명). `query` 는 이번 턴 사용자 메시지, `names`
    는 질의에서 뺄 이름, `current_turn` 은 이번 턴 번호(관련 점수의 최근성)다. `keep` 을 주면 키별 최신 행 중 그 값이 거짓인
    행을 고르기 전에 뺀다(지식 범위 필터). `scene` 은 이번 턴 장면 인물(정규형)이고 정확 조회는 그 이름이 주어·관계 대상인 행을
    `keep` 을 지난 행 사이에서 고른다. `distances` 는 질의 임베딩과 사실 행의 거리(행 id → 거리, 거리 상한으로 거른 것)이고,
    필터를 지난 행 중 거리가 있는 행의 가까운 순 목록이 비지 않으면 관련 몫의 순서는 명사 순위와 그 목록의 RRF(`rrf_k`)다."""
    # 키별 최신 뒤에서 거른다 — 앞에서 빼면 그 키의 옛 값이 지금 값처럼 되살아난다. 확인되지 않은 주장 거름은 지식 범위 필터와
    # 별도 판정이라 `keep` 이 없어도(필터 꺼짐, 아는 사람이 정해진 행 없음) 걸린다.
    winners = [
        pair
        for pair in latest_by_key(rows)
        if not unverified_claim(pair[1], user_name=user_name) and (keep is None or keep(pair[1]))
    ]
    ordered = [row for _, row in sorted(winners, key=lambda pair: (_group(pair[1]), -pair[1].importance, -pair[0]))]
    lengths = [len(fact_line(row, user_name=user_name)) for row in ordered]
    chosen: set[int] = set()
    used = 0

    def fits(i: int, limit: float) -> bool:
        return used + lengths[i] + (1 if chosen else 0) <= limit

    def take(i: int) -> None:
        nonlocal used
        used += lengths[i] + (1 if chosen else 0)
        chosen.add(i)

    def fill(limit: float, start: int = 0) -> int:
        for i in range(start, len(ordered)):
            if i in chosen:
                continue
            if not fits(i, limit):
                return i
            take(i)
        return len(ordered)

    def admit(candidates: Sequence[int], limit: float) -> None:
        for i in candidates:
            if i in chosen:
                continue
            if not fits(i, limit):
                break
            take(i)

    stop = fill(CONSTANT_RATIO * RENDER_MAX_CHARS)
    if stop < len(ordered):
        named = [i for i, row in enumerate(ordered) if _named(row, scene)]
        admit(named, (CONSTANT_RATIO + EXACT_RATIO) * RENDER_MAX_CHARS)
        relevant = _relevant(ordered, query, names, current_turn)
        near = _nearest(ordered, distances or {})
        if near:
            relevant = rrf_order([relevant, near], k=rrf_k)
        admit(relevant, RENDER_MAX_CHARS)
        fill(RENDER_MAX_CHARS, stop)
    return [ordered[i] for i in sorted(chosen)]


def _knowledge_filter(
    rows: Sequence[ChatMemoryFact],
    scope: KnowledgeScope,
    *,
    history: Sequence[ChatMessage],
    user_content: str,
    names: PromptNames,
) -> Callable[[ChatMemoryFact], bool]:
    """이번 턴의 장면 인물로 행을 남길지 정하는 판정."""
    scene = scene_for_turn(rows, scope, history=history, user_content=user_content, names=names)
    return lambda row: known_in_scene(row, scene)


async def _facts(
    db: AsyncSession,
    *,
    room_id: uuid.UUID,
    cursor: MessageKey,
    history: Sequence[ChatMessage],
    user_content: str,
    names: PromptNames,
    scope: KnowledgeScope,
    knowledge_filter: bool,
    query_vector: QueryVector | None,
) -> FactSection:
    rows = (await db.scalars(fact_rows_statement(room_id, cursor))).all()
    if not rows:
        return NO_FACTS
    distances = None
    if query_vector is not None:
        distances = await fact_distances(
            db,
            room_id=room_id,
            cursor=cursor,
            query=query_vector,
            max_distance=settings.memory_embed_recall_max_distance,
        )
    keep = None
    if knowledge_filter and any(row.known_by for row in rows):
        keep = _knowledge_filter(rows, scope, history=history, user_content=user_content, names=names)
    # 이번 턴 번호 — 오프닝을 뺀 어시스턴트 메시지 수 + 1(회상과 같은 셈, 사실 행의 끝 턴과 같은 셈이다).
    opening = opening_message(history)
    current_turn = 1 + sum(1 for m in history if m.role == ChatMessageRole.ASSISTANT and m is not opening)
    picked = select_fact_rows(
        rows,
        query=user_content,
        names=[name for name in (names.persona_name, names.char_name) if name],
        current_turn=current_turn,
        user_name=names.persona_name,
        keep=keep,
        distances=distances,
        rrf_k=settings.memory_embed_recall_rrf_k,
        scene=scene_for_turn(rows, scope, history=history, user_content=user_content, names=names),
    )
    if not picked:
        return NO_FACTS
    lines = [fact_line(row, user_name=names.persona_name) for row in picked]
    record = tuple({"factId": str(row.id), "chars": len(line)} for row, line in zip(picked, lines, strict=True))
    return FactSection("\n".join(lines), record)


async def facts_for_turn(
    db: AsyncSession,
    *,
    room_id: uuid.UUID,
    cursor: MessageKey,
    history: Sequence[ChatMessage],
    user_content: str,
    names: PromptNames,
    scope: KnowledgeScope,
    knowledge_filter: bool = False,
    query_vector: QueryVector | None = None,
) -> FactSection:
    """이번 턴의 사실 섹션. `history` 는 방의 전체 대화(턴 번호를 세고 직전 응답을 찾는다), `cursor` 는 그 턴의 요약 커서,
    `scope` 는 장면 인물을 셀 이름 출처, `knowledge_filter` 는 지식 범위 필터를 켰는가다. `query_vector` 는 임베딩 회상이 켜졌고
    질의 임베딩을 받은 턴의 질의 벡터다(None 이면 관련 몫이 명사 단독). 무엇이 실패하든 섹션
    없음이다 — 회상(`memory_recall.recall_for_turn`)과 같은 이유와 같은 방법(SAVEPOINT 로 감싼 읽기, 고르기·렌더 예외도 같은
    자리에서 받음, 스택을 실은 경고와 승격). 취소(`CancelledError`)는 `Exception` 이 아니라 그대로 올라간다."""
    try:
        async with db.begin_nested():
            return await _facts(
                db,
                room_id=room_id,
                cursor=cursor,
                history=history,
                user_content=user_content,
                names=names,
                scope=scope,
                knowledge_filter=knowledge_filter,
                query_vector=query_vector,
            )
    except Exception as exc:
        logger.warning(
            "대화방 %s 관계·사실 기억을 읽지 못해 이번 턴은 사실 섹션 없이 조립한다: %s", room_id, exc, exc_info=True
        )
        capture_dependency_failure(exc, dependency="db" if isinstance(exc, SQLAlchemyError) else "memory_fact_section")
        return NO_FACTS


async def fact_rows_from_record(db: AsyncSession, record: Sequence[dict[str, Any]]) -> list[ChatMemoryFact]:
    """턴 기록(`chat_turns.memory_facts`)의 사실 행을 기록 순서(그 턴의 줄 순서)로 — 지금 행으로 다시 고르면 그 사이 쓰인 행
    때문에 다른 글이 된다. 사실 행은 한 번 쓰면 고쳐 쓰지 않으므로 같은 id 면 같은 줄이 나온다(`fact_lines` 로 렌더한다). 기록한
    사실 중 하나라도 없으면 `FactRecordMissingError`."""
    if not record:
        return []
    ids = [uuid.UUID(str(entry["factId"])) for entry in record]
    rows = {row.id: row for row in (await db.scalars(select(ChatMemoryFact).where(ChatMemoryFact.id.in_(ids)))).all()}
    missing = [str(fact_id) for fact_id in ids if fact_id not in rows]
    if missing:
        raise FactRecordMissingError(f"턴 기록의 사실이 지금 없다: {missing}")
    return [rows[fact_id] for fact_id in ids]


def fact_lines(rows: Sequence[ChatMemoryFact], *, user_name: str | None) -> str:
    """사실 행들의 섹션 줄. `user_name` 은 그 턴 사용자의 이야기 속 이름이다(`fact_line`)."""
    return "\n".join(fact_line(row, user_name=user_name) for row in rows)
