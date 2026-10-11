"""요약 접기가 접은 대화 구간을 장면 기억(`chat_memory_episodes`)으로 뽑는다.

요약 스냅샷 하나는 대화 한 구간(직전 스냅샷 커서 다음 ~ 그 스냅샷 커서)을 접는다. 요약은 그 구간을 1,500자 한 덩이로
다시 압축하므로 오래된 장소·물건·시점 같은 디테일이 섞여 사라진다. 여기서는 같은 구간을 장면 몇 개로 나눠 한 번 쓰면 고치지
않는 행으로 남긴다 — 회상은 그 행을 명사 겹침으로 찾는다.

턴이 끝난 뒤 요청의 background 로, 그 턴의 요약 접기 **뒤에** 돈다(`chat/router.py` 의 `_fold_after_commit`). 요청 세션이 아니라
새 세션을 열고, 어떤 예외도 밖으로 내지 않는다(사용자에게 보이는 것은 없다). 사용자가 시킨 호출이 아니라서 클로버를 깎지 않고
레이트리밋에도 세지 않는다. 한 번 부르면 아직 뽑지 않은 스냅샷 중 커서가 가장 오래된 것 **하나**를 처리한다 — 밀린 것은 다음
턴의 호출이 하나씩 따라잡는다.

정합의 근거는 스냅샷 행이다. 창 안 메시지를 바꾸는 모든 경로(편집·삭제·재생성·초기화·방 삭제·탈퇴)는 같은 트랜잭션에서 그
메시지를 덮는 스냅샷을 지우고(`chat/memory_rewind.py`), 그 스냅샷의 장면·추출 기록은 DB 의 CASCADE 가 함께 지운다. 그래서
"스냅샷이 남아 있다"가 "창 원문이 추출이 읽은 뒤로 바뀌지 않았다"와 같고, 마지막 쓰기 트랜잭션이 스냅샷을 먼저 잠가 그것을
확인한다. 요약 편집은 스냅샷을 제자리에서 고치고 창 원문은 그대로라 추출을 버리지 않는다.

이 모듈은 방의 기억 노트 컬럼을 읽지도 쓰지도 않는다. 노트·스탯·계정 정보는 추출 입력에 넣지 않는다(요약과 같은 이유) —
테스트가 이 모듈 소스에 그 컬럼 이름이 없음을 확인한다."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import ColumnElement, and_, func, literal_column, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.memory_nouns import episode_nouns
from api.chat.memory_window import MessageKey, opening_message
from api.chat.prompt_builder import (
    MemoryEpisodeItem,
    MemoryEpisodeResult,
    PromptNames,
    PromptRenderError,
    build_memory_episode_prompt,
)
from api.core.sentry import capture_dependency_failure
from api.db.models import (
    ChatMemoryEpisode,
    ChatMemoryExtraction,
    ChatMessage,
    ChatMessageRole,
    ChatRoomMemorySnapshot,
    PromptSection,
    PromptSet,
)
from api.db.models.chat import (
    EPISODE_DETAIL_MAX,
    EPISODE_EVIDENCE_MAX,
    EPISODE_KEYWORDS_MAX,
    EPISODE_TITLE_MAX,
    EpisodeAssertedBy,
)
from api.llm.client import CallUsage, LLMCallContext, LLMCallSite, LLMClient, LLMClientError, dependency_tag

logger = logging.getLogger(__name__)

_EPISODE_CALL_SITE: LLMCallSite = "chat_memory_episode"

# 한 구간에서 남기는 장면 수의 상한. 빈 장면을 먼저 버린 뒤 앞에서부터 센다 — 빈 장면이 자리를 먹으면 구간 뒤쪽 장면이
# 잘려 그 턴들이 기억에 남지 않는다. 지시문도 같은 숫자를 말한다(넘기면 버려진다고).
MAX_EPISODES = 10
# 한 스냅샷을 쥐는 횟수의 상한(실패 뒤 다시 쥐기와 낡은 선점 다시 쥐기를 함께 센다). 같은 입력이 계속 실패하면 그 구간은
# 장면 없이 남는다 — 요약은 그대로 있어 대화는 막히지 않는다.
MAX_ATTEMPTS = 3
# 이만큼 지나도 `running` 이면 그 작업이 죽었다(배포 교체로 프로세스가 내려감)고 보고 다음 작업이 다시 쥔다.
_STALE_CLAIM: ColumnElement[timedelta] = literal_column("interval '10 minutes'")
# 앞 구간 마지막 장면 제목을 몇 개 싣는가 — 구간 경계에서 이어지는 장면에 같은 제목을 쓰게 한다.
PREVIOUS_TITLES = 2
# 본문을 자를 때 이 글자 뒤(상한 안 마지막 것)에서 자른다 — 문장 중간에서 끊지 않게.
_SENTENCE_ENDS = (".", "다", "요")
# 외래 키 위반. 스냅샷이 그사이 지워졌다는 뜻이라 경합이지 실패가 아니다.
_FOREIGN_KEY_VIOLATION = "23503"


@dataclass(frozen=True)
class EpisodeDraft:
    """정규화를 지난 장면 하나 — 그대로 행이 된다."""

    ordinal: int
    start_key: MessageKey
    end_key: MessageKey
    start_turn: int
    end_turn: int
    title: str
    detail: str
    nouns: list[str]
    keywords: list[str]
    evidence: list[str]
    asserted_by: EpisodeAssertedBy
    importance: int


class _Candidate(NamedTuple):
    snapshot_id: uuid.UUID
    # 스냅샷 행의 방이다(작업을 부른 쪽이 넘긴 방이 아니라) — 장면·추출 기록의 방은 늘 그 스냅샷의 방이어야 한다.
    room_id: uuid.UUID
    cursor: MessageKey
    # 직전 스냅샷의 (id, 커서). 첫 구간이면 None.
    previous: tuple[uuid.UUID, MessageKey] | None


def normalize_episodes(
    result: MemoryEpisodeResult, window: Sequence[ChatMessage], *, turns_before: int
) -> list[EpisodeDraft]:
    """모델 결과를 저장할 수 있는 장면으로 맞춘다. 응답 스키마에 길이·범위 제약을 두지 않으므로(제약이 있으면 넘친 응답
    하나가 파싱 실패가 된다) 상한은 여기서 자른다. 상수는 테이블 CHECK 와 같은 것이다.

    - 본문이 빈 장면을 버린 뒤 앞 `MAX_EPISODES` 개.
    - 제목은 상한에서 글자 단위로, 본문은 상한 안 마지막 문장 끝 뒤에서(없으면 글자 단위로) 자른다. 제목이 비면 본문 앞부분을
      저장한다(명사는 빈 제목 그대로 센다).
    - 중요도는 1~5 로 맞춘다. 키워드·근거는 빈 것을 버리고 상한까지.
    - 줄 번호(1부터, `window` 순서)는 1~n 으로 맞추고 뒤집혔으면 맞바꾼 뒤 메시지 키로 바꾼다.
    - 턴은 오프닝을 뺀 어시스턴트 메시지 순번이다. `window` 앞에 그런 메시지가 `turns_before` 개 있었다. 사용자 줄은 그 답이 붙을
      턴, 어시스턴트 줄은 자기 턴이라 어느 메시지든 "1 + 앞선 어시스턴트 메시지 수"다 — 그래서 시작 턴이 끝 턴보다 커지지 않는다.
    - 명사는 `memory_nouns.episode_nouns`(자른 뒤의 제목·본문으로)."""
    if not window:
        return []
    turn_at: list[int] = []
    assistants = turns_before
    for message in window:
        turn_at.append(assistants + 1)
        if message.role == ChatMessageRole.ASSISTANT:
            assistants += 1
    kept = [item for item in result.episodes if item.detail.strip()][:MAX_EPISODES]
    return [_draft(ordinal, item, window, turn_at) for ordinal, item in enumerate(kept)]


def _draft(ordinal: int, item: MemoryEpisodeItem, window: Sequence[ChatMessage], turn_at: list[int]) -> EpisodeDraft:
    detail = _cut_detail(item.detail.strip())
    title = item.title.strip()[:EPISODE_TITLE_MAX].strip()
    # 명사는 대체하기 전 제목으로 센다 — 본문 앞부분에서 끊긴 낱말 조각이 명사로 새지 않고, 평가 하네스가 같은 장면에서 내는
    # 명사와 같다. 저장 제목만 본문 앞부분으로 채운다(제목 칸은 비울 수 없다).
    nouns = episode_nouns(item.nouns, title, detail)
    title = title or detail[:EPISODE_TITLE_MAX].strip()
    last = len(window)
    start, end = (min(max(line, 1), last) - 1 for line in (item.start_line, item.end_line))
    if start > end:
        start, end = end, start
    return EpisodeDraft(
        ordinal=ordinal,
        start_key=(window[start].created_at, window[start].id),
        end_key=(window[end].created_at, window[end].id),
        start_turn=turn_at[start],
        end_turn=turn_at[end],
        title=title,
        detail=detail,
        nouns=nouns,
        keywords=_kept_texts(item.keywords, EPISODE_KEYWORDS_MAX),
        evidence=_kept_texts(item.evidence, EPISODE_EVIDENCE_MAX),
        asserted_by=item.asserted_by,
        importance=min(max(item.importance, 1), 5),
    )


def _cut_detail(detail: str) -> str:
    if len(detail) <= EPISODE_DETAIL_MAX:
        return detail
    head = detail[:EPISODE_DETAIL_MAX]
    end = max(head.rfind(mark) for mark in _SENTENCE_ENDS)
    return head[: end + 1] if end >= 0 else head.rstrip()


def _kept_texts(texts: Sequence[str], limit: int) -> list[str]:
    return [stripped for stripped in (text.strip() for text in texts) if stripped][:limit]


async def extract_pending_episode(
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
    """방에서 아직 뽑지 않은 스냅샷 하나를 장면 기억으로 뽑는다. 절대 예외를 내지 않는다.

    `prompt_set`·`sections` 는 추출 모델의 세트, `names` 는 이 작업을 예약한 턴의 이름이다(`fold_memory` 와 같다).

    1. 새 세션에서 후보를 고른다 — 추출 기록이 없거나, 실패했거나, `running` 인 채 10분 넘은 스냅샷 중 시도가 3회 미만인 것.
       정렬은 스냅샷 커서 오름차순 하나다. 그 직전 스냅샷의 커서도 함께 읽는다.
    2. 선점: 추출 기록을 `running` 으로 넣거나(다시 쥘 수 있는 행이면) 시도를 하나 올리고 선점 시각을 받아 곧바로 커밋한다.
       0행이면 다른 작업이 쥐었거나 상한이다. 스냅샷이 그사이 지워져 외래 키에 걸리면 경합이라 그냥 끝낸다.
    3. 창 메시지(오프닝 제외)·창 앞 어시스턴트 메시지 수·직전 스냅샷 장면의 마지막 제목들을 읽고 세션을 닫는다.
    4. 세션 없이 모델을 부른다 — 기다리는 동안 커넥션을 쥐지 않는다.
    5. 정규화(`normalize_episodes`).
    6. 새 세션 한 트랜잭션: **먼저 스냅샷을 `FOR KEY SHARE` 로 잠근다**(없으면 되감겼다 — 끝). 그다음 추출 기록을 "내 선점 시각
       그대로일 때만" `done` 으로 바꾸고(0행이면 10분 넘게 걸려 다른 작업이 다시 쥐었다 — 버린다) 장면을 넣고 커밋한다.
       스냅샷을 먼저 잡는 이유는 교착이다. 되감기는 스냅샷을 지우고(`FOR UPDATE`) CASCADE 로 추출 기록을 지운다. 추출이
       추출 기록을 먼저 잡고 나서 장면 INSERT 의 외래 키 확인으로 스냅샷을 기다리면, 스냅샷을 쥔 되감기가 추출 기록을 기다려
       서로를 기다린다. 둘 다 스냅샷부터 잡으면 한 방향으로만 줄을 선다. 같은 이유로 되감기도 장면·추출 기록을 스냅샷보다
       먼저 지우지 않는다.
    7. 실패(렌더·모델·파싱·제약 위반·DB)는 Bugsink 로 올리고 내 선점 그대로일 때만 `failed` 로 적는다(시도는 2에서 셌다).
       외래 키 위반만은 경합이라 실패로 세지 않는다. 취소는 통과시킨다.
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
            window, turns_before = await _load_window(session, candidate)
            previous_titles = await _previous_titles(session, candidate)

        prompt = build_memory_episode_prompt(
            prompt_set=prompt_set,
            sections=sections,
            is_story_chat=is_story_chat,
            previous_titles=previous_titles,
            turns=window,
            names=names,
        )
        if not prompt:
            raise PromptRenderError("장면 기억 channel 이 비어 있다 — 활성 세트에 추출 지시문이 없다")
        result = await llm_client.generate_structured(
            prompt,
            MemoryEpisodeResult,
            usage=LLMCallContext(
                call_site=_EPISODE_CALL_SITE, user_id=user_id, room_id=candidate.room_id, usage_sink=usage_sink
            ),
        )
        drafts = normalize_episodes(result, window, turns_before=turns_before)

        async with session_factory() as session:
            if not await _lock_snapshot(session, candidate.snapshot_id):
                return
            if not await _finish_claim(session, candidate.snapshot_id, claimed_at, len(drafts), usage_sink):
                logger.warning(
                    "스냅샷 %s 장면 기억 추출 결과를 버린다 — 그사이 다른 작업이 다시 쥐었다", candidate.snapshot_id
                )
                return
            session.add_all(_episode_rows(candidate, drafts))
            try:
                await session.commit()
            except IntegrityError as exc:
                if _sqlstate(exc) != _FOREIGN_KEY_VIOLATION:
                    raise
                logger.warning("스냅샷 %s 장면 기억을 넣지 못했다 — 그사이 되감겼다", candidate.snapshot_id)
    # `BaseException`이 아니라 `Exception` — 클라이언트가 끊어 생긴 취소까지 삼키면 요청 정리가 막힌다.
    except Exception as exc:
        logger.warning("대화방 %s 장면 기억 추출 실패 — 다음 턴 뒤에 다시 시도한다: %s", room_id, exc)
        capture_dependency_failure(exc, dependency=_dependency_tag(exc))
        if candidate is not None and claimed_at is not None:
            await _mark_failed(session_factory, candidate.snapshot_id, claimed_at, usage_sink)


def _retryable() -> ColumnElement[bool]:
    """이미 있는 추출 기록을 다시 쥘 수 있는가 — 실패했거나 낡은 선점이고, 시도가 상한 아래."""
    extraction = ChatMemoryExtraction
    return and_(
        extraction.attempts < MAX_ATTEMPTS,
        or_(
            extraction.status == "failed",
            and_(extraction.status == "running", extraction.claimed_at < func.clock_timestamp() - _STALE_CLAIM),
        ),
    )


async def _next_candidate(session: AsyncSession, room_id: uuid.UUID) -> _Candidate | None:
    snapshot, extraction = ChatRoomMemorySnapshot, ChatMemoryExtraction
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
            select(snapshot.id, snapshot.cursor_created_at, snapshot.cursor_message_id)
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
        previous=(previous.id, (previous.cursor_created_at, previous.cursor_message_id)) if previous else None,
    )


async def _claim(session: AsyncSession, candidate: _Candidate) -> datetime | None:
    """추출 기록을 `running` 으로 쥐고 커밋한다. 선점 시각은 문장 실행 시각(`clock_timestamp()`)이라 이 작업만의 표지가 된다."""
    extraction = ChatMemoryExtraction
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
        logger.warning("스냅샷 %s 장면 기억 추출을 건너뛴다 — 고른 뒤 되감겼다", candidate.snapshot_id)
        return None
    return claimed_at


async def _load_window(session: AsyncSession, candidate: _Candidate) -> tuple[list[ChatMessage], int]:
    """창 메시지(키 순, 오프닝 제외)와 창 앞의 오프닝 아닌 어시스턴트 메시지 수. 오프닝 판별은 윈도우·접기와 같은 규칙
    (`opening_message`)이라 방의 첫 메시지를 따로 한 줄 읽는다."""
    order = (ChatMessage.created_at.asc(), ChatMessage.id.asc())
    in_room = ChatMessage.chat_room_id == candidate.room_id
    key = tuple_(ChatMessage.created_at, ChatMessage.id)
    opening = opening_message((await session.scalars(select(ChatMessage).where(in_room).order_by(*order).limit(1))).all())
    query = select(ChatMessage).where(in_room, key <= candidate.cursor)
    if candidate.previous is not None:
        query = query.where(key > candidate.previous[1])
    window = [
        message
        for message in (await session.scalars(query.order_by(*order))).all()
        if opening is None or message.id != opening.id
    ]
    if candidate.previous is None:
        return window, 0
    before = (
        select(func.count())
        .select_from(ChatMessage)
        .where(in_room, ChatMessage.role == ChatMessageRole.ASSISTANT, key <= candidate.previous[1])
    )
    if opening is not None:
        before = before.where(ChatMessage.id != opening.id)
    return window, int(await session.scalar(before) or 0)


async def _previous_titles(session: AsyncSession, candidate: _Candidate) -> list[str]:
    """직전 스냅샷 장면의 마지막 제목들(일어난 순서). 직전 스냅샷이 없거나 아직 뽑지 않았으면 빈 목록 — 섹션째 빠진다."""
    if candidate.previous is None:
        return []
    titles = (
        await session.scalars(
            select(ChatMemoryEpisode.title)
            .where(ChatMemoryEpisode.snapshot_id == candidate.previous[0])
            .order_by(ChatMemoryEpisode.ordinal.desc())
            .limit(PREVIOUS_TITLES)
        )
    ).all()
    return list(reversed(titles))


async def _lock_snapshot(session: AsyncSession, snapshot_id: uuid.UUID) -> bool:
    """마지막 트랜잭션의 첫 문장 — 스냅샷을 `FOR KEY SHARE` 로 잠근다(요약 편집의 제자리 UPDATE 는 막지 않고, 되감기의 DELETE
    는 이 트랜잭션이 끝날 때까지 기다리게 한다). 없으면 되감겼다."""
    locked = await session.scalar(
        select(ChatRoomMemorySnapshot.id)
        .where(ChatRoomMemorySnapshot.id == snapshot_id)
        .with_for_update(read=True, key_share=True)
    )
    return locked is not None


async def _finish_claim(
    session: AsyncSession, snapshot_id: uuid.UUID, claimed_at: datetime, episode_count: int, usage: list[CallUsage]
) -> bool:
    """추출 기록을 `done` 으로 바꾼다 — 내 선점 시각 그대로일 때만. 모델 id 와 토큰은 사용량 기록과 같은 뜻이다."""
    extraction = ChatMemoryExtraction
    finished = await session.scalar(
        update(extraction)
        .where(
            extraction.snapshot_id == snapshot_id,
            extraction.status == "running",
            extraction.claimed_at == claimed_at,
        )
        .values(
            status="done",
            episode_count=episode_count,
            finished_at=func.clock_timestamp(),
            **_usage_values(usage),
        )
        .returning(extraction.snapshot_id)
    )
    return finished is not None


def _usage_values(usage: list[CallUsage]) -> dict[str, Any]:
    """이 시도의 사용량을 추출 기록에 **더하는** 값. 한 스냅샷 = 한 행이라 실패한 시도·다시 쥔 시도의 토큰이 같은 칸에 쌓인다
    (모델은 마지막 시도의 것). 보고되지 않은 칸은 건드리지 않는다. 캐시 쓰기 토큰 칸은 두지 않는다 — 이 호출은 캐시
    체크포인트를 보내지 않아(호출 정책 표의 `claude_cache_checkpoint` 기본값) 캐시 쓰기가 생기지 않는다."""
    if not usage:
        return {}
    extraction = ChatMemoryExtraction
    values: dict[str, Any] = {"model": usage[-1].model}
    for name in ("prompt_tokens", "cached_tokens", "output_tokens", "thoughts_tokens"):
        counts = [getattr(call, name) for call in usage]
        if all(count is None for count in counts):
            continue
        column = getattr(extraction, name)
        values[name] = func.coalesce(column, 0) + sum(count or 0 for count in counts)
    return values


def _episode_rows(candidate: _Candidate, drafts: Sequence[EpisodeDraft]) -> list[ChatMemoryEpisode]:
    return [
        ChatMemoryEpisode(
            chat_room_id=candidate.room_id,
            snapshot_id=candidate.snapshot_id,
            ordinal=draft.ordinal,
            start_created_at=draft.start_key[0],
            start_message_id=draft.start_key[1],
            end_created_at=draft.end_key[0],
            end_message_id=draft.end_key[1],
            start_turn=draft.start_turn,
            end_turn=draft.end_turn,
            title=draft.title,
            detail=draft.detail,
            nouns=draft.nouns,
            keywords=draft.keywords,
            evidence=draft.evidence,
            asserted_by=draft.asserted_by,
            importance=draft.importance,
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
    받고 나서 실패했으면(파싱 실패 등) 그 시도가 쓴 토큰도 더한다. 이 기록 자체가 실패하면 경고만 남긴다(10분 뒤 낡은
    선점으로 다시 쥔다)."""
    extraction = ChatMemoryExtraction
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
        logger.warning("스냅샷 %s 장면 기억 추출 실패를 적지 못했다: %s", snapshot_id, exc)


def _sqlstate(exc: IntegrityError) -> str | None:
    """asyncpg 드라이버 오류의 SQLSTATE. SQLAlchemy 가 감싼 원래 오류(`exc.orig`)에 `sqlstate` 로 실린다."""
    state = getattr(exc.orig, "sqlstate", None)
    return state if isinstance(state, str) else None


def _dependency_tag(exc: Exception) -> str:
    """추출 실패의 승격 태그 — 요약 접기(`chat/memory_fold.py` 의 같은 이름 함수)와 같은 규칙이다. 렌더 실패는
    `prompt_render`, LLM 실패는 공급자와 쿼터 소진 여부로 가른 태그, DB 실패는 `db`, 그 밖은 `memory_episode`."""
    if isinstance(exc, PromptRenderError):
        return "prompt_render"
    if isinstance(exc, LLMClientError):
        return dependency_tag(exc)
    if isinstance(exc, SQLAlchemyError):
        return "db"
    return "memory_episode"
