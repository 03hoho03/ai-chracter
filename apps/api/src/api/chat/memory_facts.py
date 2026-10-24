"""요약 접기가 접은 대화 구간을 관계·사실 기억(`chat_memory_facts`)으로 뽑는다.

요약 스냅샷 하나는 대화 한 구간(직전 스냅샷 커서 다음 ~ 그 스냅샷 커서)을 접는다. 요약은 그 구간을 한 덩이로 다시 압축해
누가 누구와 어떤 사이인지, 누가 무엇을 주장했고 무엇이 뒤집혔는지 같은 사실이 흐려진다. 여기서는 같은 구간에서 인물 관계와
인물 속성을 행으로 뽑아 덧붙인다 — 같은 사실의 갱신은 같은 키의 새 행이고, 지금 값은 읽는 쪽이 키마다 마지막 행으로 정한다.

흐름·잠금 순서·실패 처리는 장면 기억 추출(`chat/memory_episodes.py`)과 같다. 턴이 끝난 뒤 요청의 background 로, 그 턴의 접기와
장면 추출 **뒤에** 돈다(`chat/router.py` 의 `_fold_after_commit`). 새 세션을 열고 어떤 예외도 밖으로 내지 않는다 — background
태스크는 차례로 돌고 한 태스크가 예외를 내면 뒤 태스크가 돌지 않는다. 사용자가 시킨 호출이 아니라 클로버를 깎지 않고
레이트리밋에도 세지 않는다. 한 번 부르면 아직 뽑지 않은 스냅샷 중 커서가 가장 오래된 것 **하나**를 처리한다.

정합의 근거는 스냅샷 행이다. 창 안 메시지를 바꾸는 모든 경로는 같은 트랜잭션에서 그 메시지를 덮는 스냅샷을 지우고, 그
스냅샷의 사실·추출 기록은 DB 의 CASCADE 가 함께 지운다. 이 모듈은 사실 행을 직접 지우지 않는다 — 추출이 따로 지우면 스냅샷을
잠근 되감기와 반대 순서로 줄을 서 교착할 수 있다.

입력은 창 원문과, 그 스냅샷보다 커서가 앞인 스냅샷들에서 뽑은 사실을 키마다 최신 하나로 줄인 목록(기존 키)뿐이다. 노트·스탯·
작가 정본·장면 기억은 읽지도 쓰지도 않는다 — 테스트가 이 모듈 소스에 그 이름이 없음을 확인한다."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import ColumnElement, Executable, and_, func, literal_column, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.keyword_notes import normalize_keyword_text
from api.chat.memory_window import MessageKey, opening_message
from api.chat.prompt_builder import (
    MemoryFactItem,
    MemoryFactResult,
    PromptNames,
    PromptRenderError,
    build_memory_fact_prompt,
)
from api.chat.prompt_dump import dump_background_prompt
from api.core.sentry import capture_dependency_failure
from api.db.models import (
    ChatMemoryFact,
    ChatMemoryFactExtraction,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomMemorySnapshot,
    PromptSection,
    PromptSet,
)
from api.db.models.chat import (
    FACT_KEY_MAX,
    FACT_KNOWN_BY_MAX,
    FACT_NAME_MAX,
    FACT_PER_SNAPSHOT_MAX,
    FACT_VALUE_MAX,
    FactAssertedBy,
    FactKind,
    FactTruthStatus,
)
from api.llm.client import CallUsage, LLMCallContext, LLMCallSite, LLMClient, LLMClientError, dependency_tag

logger = logging.getLogger(__name__)

_FACT_CALL_SITE: LLMCallSite = "chat_memory_fact"

# 한 스냅샷을 쥐는 횟수의 상한(실패 뒤 다시 쥐기와 낡은 선점 다시 쥐기를 함께 센다). 같은 입력이 계속 실패하면 그 구간은
# 사실 없이 남는다 — 요약은 그대로 있어 대화는 막히지 않는다.
MAX_ATTEMPTS = 3
# 이만큼 지나도 `running` 이면 그 작업이 죽었다(배포 교체로 프로세스가 내려감)고 보고 다음 작업이 다시 쥔다.
_STALE_CLAIM: ColumnElement[timedelta] = literal_column("interval '10 minutes'")
# 추출 입력에 싣는 기존 키 줄 수의 상한 — 평가 하네스가 추출 문안을 잰 입력과 같은 값이다.
EXISTING_KEYS_MAX = 40
# 외래 키 위반. 스냅샷이 그사이 지워졌다는 뜻이라 경합이지 실패가 아니다.
_FOREIGN_KEY_VIOLATION = "23503"


@dataclass(frozen=True)
class FactDraft:
    """정규화를 지난 사실 하나 — 그대로 행이 된다."""

    ordinal: int
    kind: FactKind
    subject: str
    object: str | None
    attribute: str | None
    fact_key: str
    value: str
    truth_status: FactTruthStatus
    asserted_by: FactAssertedBy
    speaker: str | None
    known_by: list[str] | None
    importance: int
    start_key: MessageKey
    end_key: MessageKey
    start_turn: int
    end_turn: int


class _Candidate(NamedTuple):
    snapshot_id: uuid.UUID
    # 스냅샷 행의 방이다(작업을 부른 쪽이 넘긴 방이 아니라) — 사실·추출 기록의 방은 늘 그 스냅샷의 방이어야 한다.
    room_id: uuid.UUID
    cursor: MessageKey
    # 직전 스냅샷의 커서. 첫 구간이면 None.
    previous_cursor: MessageKey | None


def normalize_part(text: str | None) -> str:
    """키 한 칸의 정규형 — 키워드 매칭과 같은 정규화(NFC·casefold) 뒤 공백을 한 칸으로 줄이고 앞뒤를 지운다."""
    return " ".join(normalize_keyword_text(text or "").split())


def fact_key(kind: str, subject: str | None, target: str | None) -> str:
    """사실 키 = 종류 | 주어 | (관계는 대상, 사실은 속성). 평가 하네스와 같은 규칙이라 두 쪽이 같은 사실을 같은 키로 묶는다."""
    return "|".join(normalize_part(part) for part in (kind, subject, target))


def fact_rows_statement(room_id: uuid.UUID, cursor: MessageKey) -> Executable:
    """그 방에서 커서 이하로 접힌 스냅샷의 사실 행 전부, 쓴 순서(스냅샷 커서 순, 그 안은 순번 순)로 — 매 턴 조립이 그 턴 요약
    커서로 읽는다(사실 섹션과 회상의 비밀 장면 거름이 같은 행을 본다). 이 읽기는 대화 길이에 따라 선형으로 는다."""
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


def normalize_facts(
    result: MemoryFactResult, window: Sequence[ChatMessage], *, turns_before: int
) -> tuple[list[FactDraft], int]:
    """모델 결과를 저장할 수 있는 사실로 맞추고 (사실, 버린 행 수)를 돌려준다. 응답 스키마에 길이·범위 제약을 두지 않으므로
    상한은 여기서 자른다. 상수는 테이블 CHECK 와 같은 것이다.

    - 주어·값이 빈 행, 대상이 빈 관계, 속성이 빈 사실을 버린 뒤 앞 `FACT_PER_SNAPSHOT_MAX` 개. 넣으면 CHECK 에 걸려 구간 전체가
      실패하고, 상한을 센 뒤에 버리면 빈 행이 자리를 먹어 구간 뒤쪽 사실이 잘린다.
    - 키는 자르기 전 칸으로 만든 뒤 키 상한에서 자른다 — 칸 상한으로 자른 이름으로 만들면 앞부분이 같은 두 이름이 한 키가 된다.
    - 주어·대상·속성·화자는 앞뒤 공백을 지우고 이름 상한에서, 값은 값 상한에서 자른다. 종류에 맞지 않는 칸(관계의 속성·사실의
      대상)과 빈 화자는 NULL.
    - 아는 사람은 빈 이름을 버린 뒤 이름마다 이름 상한에서 자르고 앞에서부터 개수 상한까지. 다 비면 NULL(빈 배열은 쓰지 않는다).
    - 중요도는 1~5 로 맞춘다. 줄 번호는 장면 기억 추출과 같은 규칙으로 메시지 키·턴으로 바꾼다."""
    if not window:
        return [], len(result.facts)
    turn_at: list[int] = []
    assistants = turns_before
    for message in window:
        turn_at.append(assistants + 1)
        if message.role == ChatMessageRole.ASSISTANT:
            assistants += 1
    kept = [item for item in result.facts if _complete(item)]
    drafts = [_draft(ordinal, item, window, turn_at) for ordinal, item in enumerate(kept[:FACT_PER_SNAPSHOT_MAX])]
    return drafts, len(result.facts) - len(kept)


def _target(item: MemoryFactItem) -> str:
    return item.object if item.kind == "relation" else item.attribute


def _complete(item: MemoryFactItem) -> bool:
    return bool(item.subject.strip() and item.value.strip() and _target(item).strip())


def _cut(text: str, limit: int) -> str:
    return text.strip()[:limit].strip()


def cut_known_by(names: Sequence[str]) -> list[str] | None:
    """아는 인물 칸을 저장할 수 있게 자른다 — 빈 이름을 버리고 이름마다 `FACT_NAME_MAX`, 앞에서부터 `FACT_KNOWN_BY_MAX` 개.
    남는 게 없으면 None(공개이거나 알 수 없음 — 빈 배열은 쓰지 않는다). 상수는 테이블 CHECK 와 같은 것이고, 장면 기억 행도 같은
    CHECK 라 같은 함수로 자른다. 사용자 표기는 거르지 않는다 — 거르는 것은 읽는 쪽이다."""
    kept = [_cut(name, FACT_NAME_MAX) for name in names if name.strip()][:FACT_KNOWN_BY_MAX]
    return kept or None


def _draft(ordinal: int, item: MemoryFactItem, window: Sequence[ChatMessage], turn_at: list[int]) -> FactDraft:
    target = _cut(_target(item), FACT_NAME_MAX)
    relation = item.kind == "relation"
    last = len(window)
    start, end = (min(max(line, 1), last) - 1 for line in (item.start_line, item.end_line))
    if start > end:
        start, end = end, start
    return FactDraft(
        ordinal=ordinal,
        kind=item.kind,
        subject=_cut(item.subject, FACT_NAME_MAX),
        object=target if relation else None,
        attribute=None if relation else target,
        fact_key=fact_key(item.kind, item.subject, _target(item))[:FACT_KEY_MAX],
        value=_cut(item.value, FACT_VALUE_MAX),
        truth_status=item.truth_status,
        asserted_by=item.asserted_by,
        speaker=_cut(item.speaker, FACT_NAME_MAX) or None,
        known_by=cut_known_by(item.known_by),
        importance=min(max(item.importance, 1), 5),
        start_key=(window[start].created_at, window[start].id),
        end_key=(window[end].created_at, window[end].id),
        start_turn=turn_at[start],
        end_turn=turn_at[end],
    )


class _PriorFact(NamedTuple):
    fact_key: str
    value: str
    truth_status: str


def existing_key_lines(rows: Sequence[_PriorFact], *, limit: int = EXISTING_KEYS_MAX) -> list[str]:
    """앞 구간들의 행(쓴 순서)을 키마다 이긴 행 하나로 줄여 최근 `limit` 개를 `키 = 값 (진실 상태)` 줄로. 평가 하네스와 같은
    규칙이다: 같은 키의 마지막 행이 이기되, 반증된 값은 뒤의 같은 값 주장으로 되살아나지 않는다 — 같은 키에 같은 값의 반증
    행이 앞에 있으면 그 반증 행이 이긴다. 줄은 이긴 행이 쓰인 순서다."""
    groups: dict[str, list[tuple[int, _PriorFact]]] = {}
    for order, row in enumerate(rows):
        groups.setdefault(row.fact_key, []).append((order, row))
    winners: list[tuple[int, _PriorFact]] = []
    for members in groups.values():
        order, winner = members[-1]
        if winner.truth_status != "disproved":
            value = normalize_part(winner.value)
            disproved = [
                (o, r) for o, r in members if r.truth_status == "disproved" and normalize_part(r.value) == value
            ]
            if disproved:
                order, winner = disproved[-1]
        winners.append((order, winner))
    latest = [row for _, row in sorted(winners, key=lambda pair: pair[0])]
    latest = latest[-limit:] if limit > 0 else []
    return [f"{row.fact_key} = {row.value} ({row.truth_status})" for row in latest]


async def extract_pending_facts(
    session_factory: async_sessionmaker[AsyncSession],
    llm_client: LLMClient,
    *,
    room_id: uuid.UUID,
    user_id: uuid.UUID,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    is_story_chat: bool,
    names: PromptNames,
) -> None:
    """방에서 아직 뽑지 않은 스냅샷 하나를 관계·사실 기억으로 뽑는다. 절대 예외를 내지 않는다(취소만 통과시킨다).

    `prompt_set`·`sections` 는 사실 추출 모델의 세트, `names` 는 이 작업을 예약한 턴의 이름이다.

    1. 새 세션에서 후보를 고른다 — 사실 추출 기록이 없거나, 실패했거나, `running` 인 채 10분 넘은 스냅샷 중 시도가 3회 미만인
       것. 정렬은 스냅샷 커서 오름차순 하나다.
    2. 선점: 추출 기록을 `running` 으로 넣거나(다시 쥘 수 있는 행이면) 시도를 하나 올리고 선점 시각을 받아 곧바로 커밋한다.
       0행이면 다른 작업이 쥐었거나 상한이다. 스냅샷이 그사이 지워져 외래 키에 걸리면 경합이라 그냥 끝낸다.
    3. 방의 잊기 세대를 먼저 읽고, 창 메시지(오프닝 제외)·창 앞 어시스턴트 메시지 수·기존 키 줄을 읽고 세션을 닫는다. 세대를
       기존 키보다 먼저 읽어야 그 뒤에 커밋된 잊기를 6 에서 알아챈다.
    4. 세션 없이 모델을 부른다 — 기다리는 동안 커넥션을 쥐지 않는다.
    5. 정규화(`normalize_facts`). 버린 행이 있으면 그 수를 경고로 남긴다.
    6. 새 세션 한 트랜잭션: **먼저 스냅샷을 `FOR KEY SHARE` 로 잠근다**(없으면 되감겼다 — 끝). 잠근 뒤 방의 잊기 세대를 다시 읽어
       3 과 다르면(그사이 방 주인이 장면이나 사실을 잊게 했다) 결과를 버리고 내 선점 그대로일 때만 `failed` 로 적는다 — 기존 키로 읽은 잊은
       키를 모델이 다시 냈을 수 있다. 다음 턴 뒤에 다시 쥐며 시도 하나를 쓴다. 잊기는 스냅샷을 `FOR UPDATE` 로 잡으므로 이 잠금을
       쥔 동안에는 끝나지 않고, 이 잠금 앞에서 기다렸다면 바뀐 세대가 보인다(`chat/memory_forget.py`). 그다음 추출 기록을 "내 선점
       시각 그대로일 때만" `done` 으로 바꾸고(0행이면 다른 작업이 다시 쥐었다 — 버린다) 사실을 넣고 커밋한다. 스냅샷을 먼저 잡는
       이유는 장면 추출과 같다 — 되감기도 스냅샷부터 잡으므로 한 방향으로만 줄을 서 교착하지 않는다.
    7. 실패(렌더·모델·파싱·제약 위반·DB·그 밖의 예외)는 Bugsink 로 올리고 내 선점 그대로일 때만 `failed` 로 적는다(시도는 2에서
       셌다). 외래 키 위반만은 경합이라 실패로 세지 않는다.
    """
    claimed_at: datetime | None = None
    candidate: _Candidate | None = None
    usage_sink: list[CallUsage] = []
    try:
        async with session_factory() as session:
            candidate = await _next_candidate(session, room_id)
            if candidate is None:
                return
            claimed_at = await _claim(session, candidate)
            if claimed_at is None:
                return
            generation = await _forget_generation(session, candidate.room_id)
            window, turns_before = await _load_window(session, candidate)
            existing = existing_key_lines(await _prior_facts(session, candidate))

        prompt = build_memory_fact_prompt(
            prompt_set=prompt_set,
            sections=sections,
            is_story_chat=is_story_chat,
            existing_facts=existing,
            turns=window,
            names=names,
        )
        if not prompt:
            raise PromptRenderError("사실 기억 channel 이 비어 있다 — 활성 세트에 추출 지시문이 없다")
        dump_background_prompt(
            room_id=candidate.room_id,
            call_site=_FACT_CALL_SITE,
            schema=MemoryFactResult.__name__,
            prompt=prompt,
            log=logger,
            snapshot_id=candidate.snapshot_id,
        )
        result = await llm_client.generate_structured(
            prompt,
            MemoryFactResult,
            usage=LLMCallContext(
                call_site=_FACT_CALL_SITE, user_id=user_id, room_id=candidate.room_id, usage_sink=usage_sink
            ),
        )
        drafts, dropped = normalize_facts(result, window, turns_before=turns_before)
        if dropped:
            logger.warning(
                "스냅샷 %s 사실 기억 %d행을 버린다 — 주어·값이나 관계의 대상·사실의 속성이 비었다",
                candidate.snapshot_id,
                dropped,
            )

        async with session_factory() as session:
            if not await _lock_snapshot(session, candidate.snapshot_id):
                return
            if await _forget_generation(session, candidate.room_id) != generation:
                await session.rollback()
                logger.warning(
                    "스냅샷 %s 사실 기억 추출 결과를 버린다 — 입력을 읽은 뒤 방 주인이 장면이나 사실을 잊게 했다", candidate.snapshot_id
                )
                await _mark_failed(session_factory, candidate.snapshot_id, claimed_at, usage_sink)
                return
            if not await _finish_claim(session, candidate.snapshot_id, claimed_at, len(drafts), usage_sink):
                logger.warning(
                    "스냅샷 %s 사실 기억 추출 결과를 버린다 — 그사이 다른 작업이 다시 쥐었다", candidate.snapshot_id
                )
                return
            session.add_all(_fact_rows(candidate, drafts))
            try:
                await session.commit()
            except IntegrityError as exc:
                if _sqlstate(exc) != _FOREIGN_KEY_VIOLATION:
                    raise
                logger.warning("스냅샷 %s 사실 기억을 넣지 못했다 — 그사이 되감겼다", candidate.snapshot_id)
    # `BaseException`이 아니라 `Exception` — 클라이언트가 끊어 생긴 취소까지 삼키면 요청 정리가 막힌다.
    except Exception as exc:
        logger.warning("대화방 %s 사실 기억 추출 실패 — 다음 턴 뒤에 다시 시도한다: %s", room_id, exc)
        capture_dependency_failure(exc, dependency=_dependency_tag(exc))
        if candidate is not None and claimed_at is not None:
            await _mark_failed(session_factory, candidate.snapshot_id, claimed_at, usage_sink)


def _retryable() -> ColumnElement[bool]:
    """이미 있는 추출 기록을 다시 쥘 수 있는가 — 실패했거나 낡은 선점이고, 시도가 상한 아래."""
    extraction = ChatMemoryFactExtraction
    return and_(
        extraction.attempts < MAX_ATTEMPTS,
        or_(
            extraction.status == "failed",
            and_(extraction.status == "running", extraction.claimed_at < func.clock_timestamp() - _STALE_CLAIM),
        ),
    )


async def _next_candidate(session: AsyncSession, room_id: uuid.UUID) -> _Candidate | None:
    snapshot, extraction = ChatRoomMemorySnapshot, ChatMemoryFactExtraction
    row = (
        await session.execute(
            select(snapshot.id, snapshot.chat_room_id, snapshot.cursor_created_at, snapshot.cursor_message_id)
            .outerjoin(extraction, extraction.snapshot_id == snapshot.id)
            .where(snapshot.chat_room_id == room_id, or_(extraction.snapshot_id.is_(None), _retryable()))
            .order_by(snapshot.cursor_created_at, snapshot.cursor_message_id)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    cursor: MessageKey = (row.cursor_created_at, row.cursor_message_id)
    previous = (
        await session.execute(
            select(snapshot.cursor_created_at, snapshot.cursor_message_id)
            .where(
                snapshot.chat_room_id == row.chat_room_id,
                tuple_(snapshot.cursor_created_at, snapshot.cursor_message_id) < cursor,
            )
            .order_by(snapshot.cursor_created_at.desc(), snapshot.cursor_message_id.desc())
            .limit(1)
        )
    ).first()
    return _Candidate(
        snapshot_id=row.id,
        room_id=row.chat_room_id,
        cursor=cursor,
        previous_cursor=(previous.cursor_created_at, previous.cursor_message_id) if previous else None,
    )


async def _claim(session: AsyncSession, candidate: _Candidate) -> datetime | None:
    """추출 기록을 `running` 으로 쥐고 커밋한다. 선점 시각은 문장 실행 시각(`clock_timestamp()`)이라 이 작업만의 표지가 된다."""
    extraction = ChatMemoryFactExtraction
    statement = (
        insert(extraction)
        .values(
            snapshot_id=candidate.snapshot_id,
            chat_room_id=candidate.room_id,
            status="running",
            attempts=1,
            claimed_at=func.clock_timestamp(),
        )
        .on_conflict_do_update(
            index_elements=[extraction.snapshot_id],
            set_={"status": "running", "attempts": extraction.attempts + 1, "claimed_at": func.clock_timestamp()},
            where=_retryable(),
        )
        .returning(extraction.claimed_at)
    )
    try:
        claimed_at: datetime | None = await session.scalar(statement)
        await session.commit()
    except IntegrityError as exc:
        if _sqlstate(exc) != _FOREIGN_KEY_VIOLATION:
            raise
        await session.rollback()
        logger.warning("스냅샷 %s 사실 기억 추출을 건너뛴다 — 고른 뒤 되감겼다", candidate.snapshot_id)
        return None
    return claimed_at


async def _load_window(session: AsyncSession, candidate: _Candidate) -> tuple[list[ChatMessage], int]:
    """창 메시지(키 순, 오프닝 제외)와 창 앞의 오프닝 아닌 어시스턴트 메시지 수. 장면 기억 추출과 같은 규칙이다."""
    order = (ChatMessage.created_at.asc(), ChatMessage.id.asc())
    in_room = ChatMessage.chat_room_id == candidate.room_id
    key = tuple_(ChatMessage.created_at, ChatMessage.id)
    opening = opening_message(
        (await session.scalars(select(ChatMessage).where(in_room).order_by(*order).limit(1))).all()
    )
    query = select(ChatMessage).where(in_room, key <= candidate.cursor)
    if candidate.previous_cursor is not None:
        query = query.where(key > candidate.previous_cursor)
    window = [
        message
        for message in (await session.scalars(query.order_by(*order))).all()
        if opening is None or message.id != opening.id
    ]
    if candidate.previous_cursor is None:
        return window, 0
    before = (
        select(func.count())
        .select_from(ChatMessage)
        .where(in_room, ChatMessage.role == ChatMessageRole.ASSISTANT, key <= candidate.previous_cursor)
    )
    if opening is not None:
        before = before.where(ChatMessage.id != opening.id)
    return window, int(await session.scalar(before) or 0)


async def _prior_facts(session: AsyncSession, candidate: _Candidate) -> list[_PriorFact]:
    """추출할 스냅샷보다 커서가 앞인 스냅샷들의 사실(쓴 순서 = 스냅샷 커서 순, 그 안은 순번 순). 뒤 스냅샷의 사실은 이 구간
    시점에 아직 일어나지 않은 일이라 싣지 않는다."""
    fact, snapshot = ChatMemoryFact, ChatRoomMemorySnapshot
    rows = (
        await session.execute(
            select(fact.fact_key, fact.value, fact.truth_status)
            .join(snapshot, snapshot.id == fact.snapshot_id)
            .where(
                snapshot.chat_room_id == candidate.room_id,
                tuple_(snapshot.cursor_created_at, snapshot.cursor_message_id) < candidate.cursor,
            )
            .order_by(snapshot.cursor_created_at, snapshot.cursor_message_id, fact.ordinal)
        )
    ).all()
    return [_PriorFact(row.fact_key, row.value, row.truth_status) for row in rows]


async def _forget_generation(session: AsyncSession, room_id: uuid.UUID) -> int | None:
    """방의 잊기 세대(방 주인이 장면이나 사실을 잊게 할 때마다 오른다). 방이 없으면 None."""
    generation: int | None = await session.scalar(
        select(ChatRoom.memory_forget_generation).where(ChatRoom.id == room_id)
    )
    return generation


async def _lock_snapshot(session: AsyncSession, snapshot_id: uuid.UUID) -> bool:
    """마지막 트랜잭션의 첫 문장 — 스냅샷을 `FOR KEY SHARE` 로 잠근다(요약 편집의 제자리 UPDATE 는 막지 않고, 되감기의 스냅샷
    삭제는 이 트랜잭션이 끝날 때까지 기다리게 한다). 없으면 되감겼다."""
    locked = await session.scalar(
        select(ChatRoomMemorySnapshot.id)
        .where(ChatRoomMemorySnapshot.id == snapshot_id)
        .with_for_update(read=True, key_share=True)
    )
    return locked is not None


async def _finish_claim(
    session: AsyncSession, snapshot_id: uuid.UUID, claimed_at: datetime, fact_count: int, usage: list[CallUsage]
) -> bool:
    """추출 기록을 `done` 으로 바꾼다 — 내 선점 시각 그대로일 때만. 모델 id 와 토큰은 사용량 기록과 같은 뜻이다."""
    extraction = ChatMemoryFactExtraction
    finished = await session.scalar(
        update(extraction)
        .where(
            extraction.snapshot_id == snapshot_id,
            extraction.status == "running",
            extraction.claimed_at == claimed_at,
        )
        .values(status="done", fact_count=fact_count, finished_at=func.clock_timestamp(), **_usage_values(usage))
        .returning(extraction.snapshot_id)
    )
    return finished is not None


def _usage_values(usage: list[CallUsage]) -> dict[str, Any]:
    """이 시도의 사용량을 추출 기록에 **더하는** 값. 한 스냅샷 = 한 행이라 실패한 시도·다시 쥔 시도의 토큰이 같은 칸에 쌓인다
    (모델은 마지막 시도의 것). 보고되지 않은 칸은 건드리지 않는다. 캐시 쓰기 토큰 칸은 장면 추출과 같은 이유로 두지 않는다 —
    이 호출은 캐시 체크포인트를 보내지 않는다."""
    if not usage:
        return {}
    extraction = ChatMemoryFactExtraction
    values: dict[str, Any] = {"model": usage[-1].model}
    for name in ("prompt_tokens", "cached_tokens", "output_tokens", "thoughts_tokens"):
        counts = [getattr(call, name) for call in usage]
        if all(count is None for count in counts):
            continue
        column = getattr(extraction, name)
        values[name] = func.coalesce(column, 0) + sum(count or 0 for count in counts)
    return values


def _fact_rows(candidate: _Candidate, drafts: Sequence[FactDraft]) -> list[ChatMemoryFact]:
    return [
        ChatMemoryFact(
            chat_room_id=candidate.room_id,
            snapshot_id=candidate.snapshot_id,
            ordinal=draft.ordinal,
            kind=draft.kind,
            subject=draft.subject,
            object=draft.object,
            attribute=draft.attribute,
            fact_key=draft.fact_key,
            value=draft.value,
            truth_status=draft.truth_status,
            asserted_by=draft.asserted_by,
            speaker=draft.speaker,
            known_by=draft.known_by,
            importance=draft.importance,
            start_created_at=draft.start_key[0],
            start_message_id=draft.start_key[1],
            end_created_at=draft.end_key[0],
            end_message_id=draft.end_key[1],
            start_turn=draft.start_turn,
            end_turn=draft.end_turn,
        )
        for draft in drafts
    ]


async def _mark_failed(
    session_factory: async_sessionmaker[AsyncSession],
    snapshot_id: uuid.UUID,
    claimed_at: datetime,
    usage: list[CallUsage],
) -> None:
    """내 선점 그대로일 때만 `failed` 로 적는다 — 그사이 다른 작업이 다시 쥐었으면 그 작업의 기록을 건드리지 않는다. 응답을
    받고 나서 실패했으면 그 시도가 쓴 토큰도 더한다. 이 기록 자체가 실패하면 경고만 남긴다(10분 뒤 낡은 선점으로 다시 쥔다)."""
    extraction = ChatMemoryFactExtraction
    try:
        async with session_factory() as session:
            await session.execute(
                update(extraction)
                .where(
                    extraction.snapshot_id == snapshot_id,
                    extraction.status == "running",
                    extraction.claimed_at == claimed_at,
                )
                .values(status="failed", **_usage_values(usage))
            )
            await session.commit()
    except Exception as exc:
        logger.warning("스냅샷 %s 사실 기억 추출 실패를 적지 못했다: %s", snapshot_id, exc)


def _sqlstate(exc: IntegrityError) -> str | None:
    """asyncpg 드라이버 오류의 SQLSTATE. SQLAlchemy 가 감싼 원래 오류(`exc.orig`)에 `sqlstate` 로 실린다."""
    state = getattr(exc.orig, "sqlstate", None)
    return state if isinstance(state, str) else None


def _dependency_tag(exc: Exception) -> str:
    """추출 실패의 승격 태그 — 장면 기억 추출과 같은 규칙이다. 렌더 실패는 `prompt_render`, LLM 실패는 공급자와 쿼터 소진
    여부로 가른 태그, DB 실패는 `db`, 그 밖은 `memory_fact`."""
    if isinstance(exc, PromptRenderError):
        return "prompt_render"
    if isinstance(exc, LLMClientError):
        return dependency_tag(exc)
    if isinstance(exc, SQLAlchemyError):
        return "db"
    return "memory_fact"
