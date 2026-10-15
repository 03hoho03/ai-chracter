"""매 턴 사실 섹션 — 방의 관계·사실 기억(`chat_memory_facts`)을 키마다 지금 값으로 줄이고, 상시 몫과 이번 턴 사용자 메시지에
관련된 행을 글자 상한 안에서 골라 생성 프롬프트의 사실 섹션(대화 기록 뒤, 회상 앞)에 싣는다. LLM 을 부르지 않는다(DB 읽기 한
번과 파이썬 계산).

읽는 행: 그 턴 요약 커서 이하에서 접힌 스냅샷의 행 전부를 쓴 순서(스냅샷 커서 순, 그 안은 순번 순)로. 커서 뒤는 원문 윈도우로
이미 실리고, 지난 턴을 그때의 커서로 다시 조립하면 그 뒤에 접힌 스냅샷의 행은 그때 없던 사실이다. 되감기는 스냅샷을 지우고
DB 가 그 행을 함께 지우므로 다음 읽기에 앞 값이 돌아온다.

키별 최신: 같은 키의 마지막 행이 이기되, 같은 키에 같은 값의 반증 행이 앞에 있으면 그 반증 행이 이긴다 — 반증된 값이 뒤의
같은 값 주장으로 되살아나지 않게. 값이 다른 새 행은 옛 값의 반증 행에 가려지지 않는다(정정). 사실 추출이 추출 입력의 기존 키
목록을 만드는 규칙(`chat/memory_facts.py` 의 `existing_key_lines`)과 같다.

렌더 순서: 관계 → 아는 사람이 정해진 사실 → 반증 → 그 밖. 묶음 안은 중요도가 높은 쪽, 같으면 나중에 쓴 쪽이 먼저다.

고르기(줄 비용 = 줄 글자 수 + 첫 줄 뒤마다 줄바꿈 1): 렌더 순서 전부가 상한 안이면 전부. 아니면 ① 렌더 순서로 상한의
`CONSTANT_RATIO` 까지(다음 줄이 넘으면 멈춤) ② 이번 턴 사용자 메시지와 명사가 겹치고 점수가 `RELEVANCE_TAU` 이상인 행을 순위대로
상한까지(다음 줄이 넘으면 멈춤) ③ 남은 자리를 ①이 멈춘 곳부터 렌더 순서로 다시 채운다(다음 줄이 넘으면 멈추고 뒤의 짧은 줄로
건너뛰지 않는다). 실린 행은 렌더 순서로 쓴다. 관련 점수는 장면 회상의 토큰·점수 함수를 그대로 쓴다(행 명사 = 주어·대상이나
속성·값의 조사 뗀 토큰, 질의에서 이름·불용어·방 행의 20% 넘게 나오는 명사를 뺀다, 행 5개 미만이면 관련 행 없음).

지식 범위 필터(`chat/memory_knowledge.py`, 호출부가 켰을 때만): 키별 최신 행 중 아는 사람이 이번 장면에 없는 행을 고르기
전에 뺀다 — 빠진 자리는 다음 후보가 채우고, 같은 키의 앞 값이 지금 값처럼 되살아나지 않는다. 이름 출처는 읽은 사실 행을 그대로
쓰고, 스토리 방은 작품 버전의 미디어 북 인물을 한 번 더 읽는다(아는 사람이 정해진 행이 없으면 걸러 낼 것이 없어 읽지 않는다).

상수와 고르기는 평가 하네스의 시제품을 개발 절반 격자로 맞춘 값과 절차다. 줄 모양만 하네스와 다르다 — 운영 섹션 문안이 설명하는
꼬리표를 쓴다.

읽기는 요청 세션의 SAVEPOINT 안이고, DB 오류든 그 밖의 예외든 경고·승격을 남기고 섹션 없이 조립한다(생성 프롬프트 조립은 SSE
제너레이터 본문 안이라 예외가 새면 무관한 요청까지 500 이 된다)."""

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Executable, select, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import memory_recall
from api.chat.keyword_notes import recent_scan_turns
from api.chat.memory_facts import normalize_part
from api.chat.memory_knowledge import known_in_scene, room_names, scene_people, user_names
from api.chat.memory_nouns import rule_tokens
from api.chat.memory_recall import RecallCandidate, query_tokens, score_episodes
from api.chat.memory_window import MessageKey, opening_message
from api.chat.prompt_builder import PromptNames
from api.core.sentry import capture_dependency_failure
from api.db.models.chat import ChatMemoryFact, ChatMessage, ChatMessageRole, ChatRoomMemorySnapshot
from api.db.models.story import MediaBookPerson

logger = logging.getLogger(__name__)

# 사실 줄을 이어 붙인 글의 상한(줄바꿈 포함 글자 수), 그중 렌더 순서로만 채우는 상시 몫, 관련 행의 점수 임계.
RENDER_MAX_CHARS = 700
CONSTANT_RATIO = 0.3
RELEVANCE_TAU = 0.6
# 뒤집힌 사실의 줄 앞 표지. 뜻은 사실 섹션 문안이 설명한다.
DISPROVED_MARK = "(사실 아님으로 밝혀짐) "


@dataclass(frozen=True)
class FactSection:
    """이번 턴의 사실 섹션 — 섹션에 실을 줄(없으면 `""`)과 턴 기록 칸에 남길 목록 `[{factId, chars}]`(줄 순서)."""

    lines: str
    record: tuple[dict[str, Any], ...]


NO_FACTS = FactSection("", ())


@dataclass(frozen=True)
class KnowledgeScope:
    """지식 범위 필터를 켠 턴에 호출부가 넘기는 이름 출처 — 그 턴 생성 프롬프트 세트의 대화 줄 라벨(사용자 표기)과, 스토리 방이면
    미디어 북 인물을 읽을 작품 버전 id(캐릭터 방은 None — 작품 이름은 `PromptNames.char_name` 으로 이미 안다)."""

    user_label: str
    media_book_version_id: uuid.UUID | None


class FactRecordMissingError(Exception):
    """턴 기록에 남은 사실이 지금 DB 에 없다(그 뒤 되감기로 지워졌다)."""


def fact_line(row: ChatMemoryFact, *, user_name: str | None = None) -> str:
    """사실 한 줄. 꼬리표는 이 순서로 붙는다 — 반증이면 줄 앞 표지, 주장이면 끝에 말한 쪽, 아는 사람이 있으면 그 뒤에
    `(이름·이름만 앎)`. 말한 쪽은 사용자가 내놓은 주장이거나 말한 사람이 그 턴 사용자의 이야기 속 이름(`user_name`, 사실 키와
    같은 정규화로 견준다)이면 사용자 꼬리표다 — 추출이 사용자 말을 그 이름의 인물 말로 적어도 사용자가 한 말로 읽히게. 그 밖은
    말한 인물 이름, 이름이 없으면 인물 꼬리표다. 사용자·인물 꼬리표는 회상 줄과 같은 상수다(두 섹션 문안이 같은 꼬리표를
    설명한다)."""
    if row.kind == "relation":
        line = f"{row.subject} → {row.object}: {row.value}"
    else:
        line = f"{row.subject} · {row.attribute}: {row.value}"
    if row.truth_status == "disproved":
        line = DISPROVED_MARK + line
    elif row.truth_status == "claimed":
        spoken_by_user = bool(user_name and row.speaker and normalize_part(row.speaker) == normalize_part(user_name))
        if row.asserted_by == "user" or spoken_by_user:
            line += memory_recall.USER_ASSERTION_TAIL
        elif row.speaker:
            line += f" ({row.speaker}의 말)"
        else:
            line += memory_recall.CHARACTER_ASSERTION_TAIL
    if row.known_by:
        line += f" ({'·'.join(row.known_by)}만 앎)"
    return f"- {line}"


def _latest_by_key(rows: Sequence[ChatMemoryFact]) -> list[tuple[int, ChatMemoryFact]]:
    """키마다 이긴 행 하나와 그 행의 쓴 순번(규칙은 모듈 설명)."""
    groups: dict[str, list[tuple[int, ChatMemoryFact]]] = {}
    for order, row in enumerate(rows):
        groups.setdefault(row.fact_key, []).append((order, row))
    winners: list[tuple[int, ChatMemoryFact]] = []
    for members in groups.values():
        winner = members[-1]
        if winner[1].truth_status != "disproved":
            value = normalize_part(winner[1].value)
            disproved = [m for m in members if m[1].truth_status == "disproved" and normalize_part(m[1].value) == value]
            if disproved:
                winner = disproved[-1]
        winners.append(winner)
    return winners


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


def select_fact_rows(
    rows: Sequence[ChatMemoryFact],
    *,
    query: str,
    names: Sequence[str],
    current_turn: int,
    user_name: str | None = None,
    keep: Callable[[ChatMemoryFact], bool] | None = None,
) -> list[ChatMemoryFact]:
    """쓴 순서의 행 전부에서 섹션에 실을 행을 렌더 순서로 고른다(규칙은 모듈 설명). `query` 는 이번 턴 사용자 메시지, `names`
    는 질의에서 뺄 이름, `current_turn` 은 이번 턴 번호(관련 점수의 최근성)다. `keep` 을 주면 키별 최신 행 중 그 값이 거짓인
    행을 고르기 전에 뺀다(지식 범위 필터)."""
    winners = _latest_by_key(rows)
    if keep is not None:
        winners = [pair for pair in winners if keep(pair[1])]
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

    stop = fill(CONSTANT_RATIO * RENDER_MAX_CHARS)
    if stop < len(ordered):
        for i in _relevant(ordered, query, names, current_turn):
            if i in chosen:
                continue
            if not fits(i, RENDER_MAX_CHARS):
                break
            take(i)
        fill(RENDER_MAX_CHARS, stop)
    return [ordered[i] for i in sorted(chosen)]


def _fact_statement(room_id: uuid.UUID, cursor: MessageKey) -> Executable:
    """그 방에서 커서 이하로 접힌 스냅샷의 사실 행 전부, 쓴 순서(스냅샷 커서 순, 그 안은 순번 순)로. 이 읽기는 대화 길이에 따라
    선형으로 는다."""
    fact, snapshot = ChatMemoryFact, ChatRoomMemorySnapshot
    return (
        select(fact)
        .join(snapshot, snapshot.id == fact.snapshot_id)
        .where(
            fact.chat_room_id == room_id,
            tuple_(snapshot.cursor_created_at, snapshot.cursor_message_id) <= cursor,
        )
        .order_by(snapshot.cursor_created_at, snapshot.cursor_message_id, fact.ordinal)
    )


def _media_book_statement(version_id: uuid.UUID) -> Executable:
    """작품 버전의 미디어 북 인물 이름."""
    return select(MediaBookPerson.name).where(MediaBookPerson.content_version_id == version_id)


async def _knowledge_filter(
    db: AsyncSession,
    rows: Sequence[ChatMemoryFact],
    scope: KnowledgeScope,
    *,
    history: Sequence[ChatMessage],
    user_content: str,
    names: PromptNames,
) -> Callable[[ChatMemoryFact], bool]:
    """이번 턴의 장면 인물로 행을 남길지 정하는 판정. 직전 응답은 키워드북·회상과 같은 스캔 글(이미지 태그를 지우고
    `{{user}}`·`{{char}}` 를 이름으로 바꾼 것)이다."""
    extra = [names.char_name] if names.char_name else []
    if scope.media_book_version_id is not None:
        extra += (await db.scalars(_media_book_statement(scope.media_book_version_id))).all()
    previous_response = recent_scan_turns(history, user_content, 0, names=names)[0].assistant_text
    users = user_names(names.persona_name, scope.user_label)
    scene = scene_people(room_names(rows, extra, users=users), (user_content, previous_response))
    return lambda row: known_in_scene(row, scene)


async def _facts(
    db: AsyncSession,
    *,
    room_id: uuid.UUID,
    cursor: MessageKey,
    history: Sequence[ChatMessage],
    user_content: str,
    names: PromptNames,
    knowledge: KnowledgeScope | None,
) -> FactSection:
    rows = (await db.scalars(_fact_statement(room_id, cursor))).all()
    if not rows:
        return NO_FACTS
    keep = None
    if knowledge is not None and any(row.known_by for row in rows):
        keep = await _knowledge_filter(db, rows, knowledge, history=history, user_content=user_content, names=names)
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
    knowledge: KnowledgeScope | None = None,
) -> FactSection:
    """이번 턴의 사실 섹션. `history` 는 방의 전체 대화(턴 번호를 세고 직전 응답을 찾는다), `cursor` 는 그 턴의 요약 커서,
    `knowledge` 는 지식 범위 필터를 켰을 때의 이름 출처다(None 이면 필터 없이 고른다). 무엇이 실패하든 섹션
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
                knowledge=knowledge,
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
