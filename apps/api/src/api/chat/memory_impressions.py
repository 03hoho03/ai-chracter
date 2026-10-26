"""요약 접기 몇 번마다 방 하나에 인상(`chat_memory_impressions`) 한 행을 쌓는다 — 그 접기들에서 뽑힌 장면·사실 기억을 읽고
인물 사이 감정·태도의 흐름을 짧은 글로 적는다. 저장만 한다: 생성 프롬프트에 싣지 않고 화면에도 보이지 않는다.

턴이 끝난 뒤 요청의 background 로, 그 턴의 접기와 두 추출 **뒤에** 돈다(`chat/router.py` 의 `_fold_after_commit`, 스위치
`memory_impressions_write`). 새 세션을 열고 어떤 예외도 밖으로 내지 않는다 — background 태스크는 차례로 돌고 한 태스크가 예외를
내면 뒤 태스크가 돌지 않는다. 사용자가 시킨 호출이 아니라 클로버를 깎지 않고 레이트리밋에도 세지 않는다.

언제 만드나 — 방의 스냅샷을 커서 순으로 세어 그 수가 N(`memory_impression_every_n_folds`)의 배수일 때, 가장 새 스냅샷까지 N 개를
한 묶음으로 본다. 가장 새 스냅샷에 인상이 아직 없고 묶음의 모든 스냅샷이 장면·사실 추출을 둘 다 끝냈을 때(`done`)만 모델을
부른다 — 추출이 덜 된 묶음으로 만들면 반쪽 입력이다. 늘 가장 새 묶음만 본다: 다음 접기가 스냅샷을 하나 더하면 그 묶음은 더 이상
보지 않으므로, 스위치를 켜기 전의 대화나 추출이 끝내 실패한 묶음을 거슬러 채우지 않는다. 그 턴의 레인과 글쓰기 모델이 기억 사용
범위(`memory_model_scope`) 밖이면 아무것도 읽지 않는다 — 판정은 접기와 같이 받은 세트의 레인과 그 턴에 응답을 쓴 모델로 한다.

입력 — 묶음 스냅샷의 장면·사실 행 전부다. 아는 사람(`known_by`)이 정해진 행도 넣는다: 장면 추출이 그 장면에 있던 인물을 거의
늘 아는 사람으로 적어서, 그런 행을 빼면 장면 대부분이 빠지고 인상이 사실 줄에만 기댄다. 요약 글·원문 대화·노트는 읽지 않는다.
인상 행은 입력에 쓴 장면·사실 행 id 를 전부 근거(`episode_ids`·`fact_ids`)로 남긴다. 인상은 방 주인만 보는 기억 보기에 보이고
(방 주인은 비밀 행도 이미 다 본다) 생성 프롬프트에 싣지 않으므로 여기서 거르지 않는다 — 인상을 프롬프트에 싣게 되면 그 쪽이
근거 행 단위로(근거 중 그 자리에서 보이면 안 되는 행이 있는 인상을 빼는 식으로) 거른다.

쓰기 — 잠금 순서는 두 추출과 같다. 입력을 읽기 전에 방의 잊기 세대를 읽어 두고, 마지막 트랜잭션에서 **먼저** 가장 새 스냅샷을
`FOR KEY SHARE` 로 잠근 뒤(없으면 되감겼다 — 끝) 세대를 다시 읽어 다르면 결과를 버린다(그사이 방 주인이 장면이나 사실을 잊게
했다 — 결과에 잊은 내용이 들어 있을 수 있다). 잊게 하기는 그 방 스냅샷을 전부 `FOR UPDATE` 로 잡고 그 방의 인상을 전부 지우므로,
이 잠금을 쥔 동안에는 끝나지 않고 커밋을 기다렸다가 방금 넣은 행까지 지운다(`chat/memory_forget.py`). 세대를 잠금 전에 다시 읽으면
그 사이에 커밋된 잊기를 놓친다. 인상 행은 여기서 지우지 않는다 — 되감기는 스냅샷 DELETE 의 CASCADE 가 지운다.

시도 기록 — 묶음마다(가장 새 스냅샷마다) 시도 기록(`chat_memory_impression_attempts`) 한 행을 두 추출 기록과 같은 꼴로 쓴다.
모델을 부르기 전에 그 행을 `running` 으로 쥐고 곧바로 커밋한다 — 같은 묶음을 고른 다른 작업은 선점에서 지고 모델을 부르지 않는다.
모델 실패·빈 글·렌더 실패·잊기 세대 불일치·그 밖의 예외는 `failed` 로 적고(내 선점 그대로일 때만), 다음 턴 뒤에 다시 쥐되 시도는
세 번까지다. 10분이 지나도 `running` 이면 작업이 죽었다고 보고 다시 쥔다. 성공하면 인상 행과 같은 트랜잭션에서 `done` 으로 바꾸고
모델 id 와 토큰을 남긴다(실패한 시도의 토큰도 더한다). 다시 보는 것도 그 묶음이 가장 새 묶음인 동안(다음 접기 전까지)만이다.
같은 묶음의 인상 행이 그래도 두 번 들어가려 하면 스냅샷 유니크가 뒤의 것을 막는다(경합이라 실패로 세지 않는다)."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, func, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.memory_window import MessageKey, memory_model_in_scope
from api.chat.prompt_builder import MemoryImpressionResult, PromptRenderError, build_memory_impression_prompt
from api.chat.prompt_dump import dump_background_prompt
from api.core.config import settings
from api.core.sentry import capture_dependency_failure
from api.db.models import (
    ChatMemoryEpisode,
    ChatMemoryExtraction,
    ChatMemoryFact,
    ChatMemoryFactExtraction,
    ChatMemoryImpression,
    ChatMemoryImpressionAttempt,
    ChatRoom,
    ChatRoomMemorySnapshot,
    PromptSection,
    PromptSet,
)
from api.db.models.chat import IMPRESSION_TEXT_MAX
from api.llm.chat_models import ChatModelId
from api.llm.client import CallUsage, LLMCallContext, LLMCallSite, LLMClient, LLMClientError, dependency_tag

logger = logging.getLogger(__name__)

_IMPRESSION_CALL_SITE: LLMCallSite = "chat_memory_impression"

# 한 묶음을 쥐는 횟수의 상한(실패 뒤 다시 쥐기와 낡은 선점 다시 쥐기를 함께 센다) — 두 추출과 같은 값이다. 같은 입력이 계속
# 실패하면 그 묶음은 인상 없이 남는다 — 인상은 생성에 쓰이지 않아 대화는 막히지 않는다.
MAX_ATTEMPTS = 3
# 이만큼 지나도 `running` 이면 그 작업이 죽었다(배포 교체로 프로세스가 내려감)고 보고 다음 작업이 다시 쥔다.
_STALE_CLAIM: ColumnElement[timedelta] = literal_column("interval '10 minutes'")

# 외래 키 위반(스냅샷이 그사이 지워졌다)과 유니크 위반(다른 작업이 같은 묶음을 먼저 넣었다). 둘 다 경합이지 실패가 아니다.
_FOREIGN_KEY_VIOLATION = "23503"
_UNIQUE_VIOLATION = "23505"


@dataclass(frozen=True)
class _Group:
    room_id: uuid.UUID
    # 묶음 스냅샷 id, 커서 순. 마지막이 인상 행이 걸리는 가장 새 스냅샷이다.
    snapshot_ids: list[uuid.UUID]
    first_cursor: MessageKey

    @property
    def anchor_id(self) -> uuid.UUID:
        return self.snapshot_ids[-1]


def episode_line(row: ChatMemoryEpisode) -> str:
    """입력의 장면 한 줄 — `- 제목: 내용`."""
    return f"- {row.title}: {row.detail}"


def fact_line(row: ChatMemoryFact) -> str:
    """입력의 사실 한 줄 — 관계는 `- 주어 → 대상: 값 (진실 상태)`, 속성은 `- 주어 / 속성: 값 (진실 상태)`."""
    target = f"→ {row.object}" if row.kind == "relation" else f"/ {row.attribute}"
    return f"- {row.subject} {target}: {row.value} ({row.truth_status})"


async def generate_pending_impression(
    session_factory: async_sessionmaker[AsyncSession],
    llm_client: LLMClient,
    *,
    room_id: uuid.UUID,
    user_id: uuid.UUID,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    is_story_chat: bool,
    writing_model: ChatModelId,
) -> None:
    """방의 가장 새 묶음이 찼으면 인상 한 행을 만든다. 절대 예외를 내지 않는다(취소만 통과시킨다).

    `prompt_set`·`sections` 는 인상 모델의 세트, `writing_model` 은 이 작업을 예약한 턴에 응답을 쓴 모델이다(범위 판정용).

    1. 범위 밖이면 끝 — 아무것도 읽지도 쓰지도 않는다.
    2. 새 세션에서 묶음을 고른다(모듈 설명 「언제 만드나」). 없으면 끝. 방의 잊기 세대를 읽은 **뒤에** 입력 행을 읽는다 — 그 뒤에
       커밋된 잊기를 5 에서 알아챈다. 입력 행이 하나도 없으면 쥐지도 부르지도 않는다.
    3. 같은 세션에서 선점: 시도 기록을 `running` 으로 넣거나(다시 쥘 수 있는 행이면) 시도를 하나 올리고 선점 시각을 받아 곧바로
       커밋한다. 0행이면 다른 작업이 쥐었거나 상한이다 — 부르지 않고 끝. 스냅샷이 그사이 지워져 외래 키에 걸리면 경합이라 끝.
    4. 세션 없이 렌더하고 모델을 부른다. 글은 앞뒤 공백을 걷고 상한에서 자르며, 비면 `failed` 로 적는다.
    5. 새 세션 한 트랜잭션: 가장 새 스냅샷 `FOR KEY SHARE`(없으면 되감겼다 — 끝) → 세대 재확인(다르면 버리고 `failed`) → 시도
       기록을 내 선점 그대로일 때만 `done` 으로(0행이면 다른 작업이 다시 쥐었다 — 버림) → 인상 행을 넣고 커밋. 외래 키·유니크
       위반은 경합이라 경고만 남긴다.
    6. 그 밖의 실패(렌더·모델·DB·예외)는 경고와 Bugsink 로 남기고, 쥐었으면 `failed` 로 적는다."""
    if not memory_model_in_scope(prompt_set.lane, writing_model, settings.memory_model_scope):
        return
    group: _Group | None = None
    claimed_at: datetime | None = None
    usage_sink: list[CallUsage] = []
    try:
        async with session_factory() as session:
            group = await _due_group(session, room_id, settings.memory_impression_every_n_folds)
            if group is None:
                return
            generation = await _forget_generation(session, room_id)
            episodes, facts = await _load_inputs(session, group)
            if not episodes and not facts:
                return
            claimed_at = await _claim(session, group)
            if claimed_at is None:
                return

        prompt = build_memory_impression_prompt(
            sections=sections,
            is_story_chat=is_story_chat,
            episode_lines=[episode_line(row) for row in episodes],
            fact_lines=[fact_line(row) for row in facts],
        )
        if not prompt:
            raise PromptRenderError("인상 channel 이 비어 있다 — 활성 세트에 인상 지시문이 없다")
        dump_background_prompt(
            room_id=room_id,
            call_site=_IMPRESSION_CALL_SITE,
            schema=MemoryImpressionResult.__name__,
            prompt=prompt,
            log=logger,
            snapshot_id=group.anchor_id,
        )
        result = await llm_client.generate_structured(
            prompt,
            MemoryImpressionResult,
            usage=LLMCallContext(
                call_site=_IMPRESSION_CALL_SITE, user_id=user_id, room_id=room_id, usage_sink=usage_sink
            ),
        )
        text = result.impression.strip()[:IMPRESSION_TEXT_MAX].strip()
        if not text:
            logger.warning("스냅샷 %s 인상을 쓰지 않는다 — 모델이 빈 글을 냈다", group.anchor_id)
            await _mark_failed(session_factory, group.anchor_id, claimed_at, usage_sink)
            return

        async with session_factory() as session:
            if not await _lock_snapshot(session, group.anchor_id):
                return
            if await _forget_generation(session, room_id) != generation:
                await session.rollback()
                logger.warning(
                    "스냅샷 %s 인상을 버린다 — 입력을 읽은 뒤 방 주인이 장면이나 사실을 잊게 했다", group.anchor_id
                )
                await _mark_failed(session_factory, group.anchor_id, claimed_at, usage_sink)
                return
            if not await _finish_claim(session, group.anchor_id, claimed_at, usage_sink):
                logger.warning("스냅샷 %s 인상을 버린다 — 그사이 다른 작업이 다시 쥐었다", group.anchor_id)
                return
            await _insert_impression(
                session,
                ChatMemoryImpression(
                    chat_room_id=room_id,
                    snapshot_id=group.anchor_id,
                    first_cursor_created_at=group.first_cursor[0],
                    first_cursor_message_id=group.first_cursor[1],
                    text=text,
                    episode_ids=[str(row.id) for row in episodes],
                    fact_ids=[str(row.id) for row in facts],
                ),
            )
            await session.commit()
    # `BaseException`이 아니라 `Exception` — 클라이언트가 끊어 생긴 취소까지 삼키면 요청 정리가 막힌다.
    except Exception as exc:
        if isinstance(exc, IntegrityError) and _sqlstate(exc) in (_FOREIGN_KEY_VIOLATION, _UNIQUE_VIOLATION):
            logger.warning("대화방 %s 인상을 넣지 않았다 — 그사이 되감겼거나 같은 묶음이 먼저 들어갔다", room_id)
            return
        logger.warning("대화방 %s 인상 생성 실패 — 다음 턴 뒤에 다시 본다: %s", room_id, exc)
        capture_dependency_failure(exc, dependency=_dependency_tag(exc))
        if group is not None and claimed_at is not None:
            await _mark_failed(session_factory, group.anchor_id, claimed_at, usage_sink)


async def _due_group(session: AsyncSession, room_id: uuid.UUID, every: int) -> _Group | None:
    """만들 때가 된 묶음(모듈 설명 「언제 만드나」). 없으면 None."""
    snapshot = ChatRoomMemorySnapshot
    rows = (
        await session.execute(
            select(snapshot.id, snapshot.cursor_created_at, snapshot.cursor_message_id)
            .where(snapshot.chat_room_id == room_id)
            .order_by(snapshot.cursor_created_at, snapshot.cursor_message_id)
        )
    ).all()
    if not rows or len(rows) % every != 0:
        return None
    members = rows[-every:]
    ids = [row.id for row in members]
    anchor = ids[-1]
    if await session.scalar(select(ChatMemoryImpression.id).where(ChatMemoryImpression.snapshot_id == anchor)):
        return None
    for extraction in (ChatMemoryExtraction, ChatMemoryFactExtraction):
        done = await session.scalar(
            select(func.count())
            .select_from(extraction)
            .where(extraction.snapshot_id.in_(ids), extraction.status == "done")
        )
        if done != len(ids):
            return None
    return _Group(
        room_id=room_id, snapshot_ids=ids, first_cursor=(members[0].cursor_created_at, members[0].cursor_message_id)
    )


async def _load_inputs(session: AsyncSession, group: _Group) -> tuple[list[ChatMemoryEpisode], list[ChatMemoryFact]]:
    """묶음 스냅샷의 장면·사실 행 전부(아는 사람이 정해진 행 포함), 스냅샷 커서 순·그 안은 순번 순."""
    snapshot = ChatRoomMemorySnapshot
    order = (snapshot.cursor_created_at, snapshot.cursor_message_id)
    episodes = (
        await session.scalars(
            select(ChatMemoryEpisode)
            .join(snapshot, snapshot.id == ChatMemoryEpisode.snapshot_id)
            .where(ChatMemoryEpisode.snapshot_id.in_(group.snapshot_ids))
            .order_by(*order, ChatMemoryEpisode.ordinal)
        )
    ).all()
    facts = (
        await session.scalars(
            select(ChatMemoryFact)
            .join(snapshot, snapshot.id == ChatMemoryFact.snapshot_id)
            .where(ChatMemoryFact.snapshot_id.in_(group.snapshot_ids))
            .order_by(*order, ChatMemoryFact.ordinal)
        )
    ).all()
    return list(episodes), list(facts)


async def _forget_generation(session: AsyncSession, room_id: uuid.UUID) -> int | None:
    """방의 잊기 세대(방 주인이 장면이나 사실을 잊게 할 때마다 오른다). 방이 없으면 None."""
    generation: int | None = await session.scalar(
        select(ChatRoom.memory_forget_generation).where(ChatRoom.id == room_id)
    )
    return generation


async def _lock_snapshot(session: AsyncSession, snapshot_id: uuid.UUID) -> bool:
    """마지막 트랜잭션의 첫 문장 — 가장 새 스냅샷을 `FOR KEY SHARE` 로 잠근다(두 추출과 같은 잠금). 없으면 되감겼다."""
    locked = await session.scalar(
        select(ChatRoomMemorySnapshot.id)
        .where(ChatRoomMemorySnapshot.id == snapshot_id)
        .with_for_update(read=True, key_share=True)
    )
    return locked is not None


def _retryable() -> ColumnElement[bool]:
    """이미 있는 시도 기록을 다시 쥘 수 있는가 — 실패했거나 낡은 선점이고, 시도가 상한 아래."""
    attempt = ChatMemoryImpressionAttempt
    return and_(
        attempt.attempts < MAX_ATTEMPTS,
        or_(
            attempt.status == "failed",
            and_(attempt.status == "running", attempt.claimed_at < func.clock_timestamp() - _STALE_CLAIM),
        ),
    )


async def _claim(session: AsyncSession, group: _Group) -> datetime | None:
    """묶음의 시도 기록을 `running` 으로 쥐고 커밋한다. 선점 시각은 문장 실행 시각(`clock_timestamp()`)이라 이 작업만의 표지가
    된다. 다른 작업이 쥐었거나 상한이면 None, 스냅샷이 그사이 지워졌어도 None(경합 — 실패로 세지 않는다)."""
    attempt = ChatMemoryImpressionAttempt
    statement = (
        insert(attempt)
        .values(
            snapshot_id=group.anchor_id,
            chat_room_id=group.room_id,
            status="running",
            attempts=1,
            claimed_at=func.clock_timestamp(),
        )
        .on_conflict_do_update(
            index_elements=[attempt.snapshot_id],
            set_={"status": "running", "attempts": attempt.attempts + 1, "claimed_at": func.clock_timestamp()},
            where=_retryable(),
        )
        .returning(attempt.claimed_at)
    )
    try:
        claimed_at: datetime | None = await session.scalar(statement)
        await session.commit()
    except IntegrityError as exc:
        if _sqlstate(exc) != _FOREIGN_KEY_VIOLATION:
            raise
        await session.rollback()
        logger.warning("스냅샷 %s 인상을 건너뛴다 — 고른 뒤 되감겼다", group.anchor_id)
        return None
    return claimed_at


async def _finish_claim(
    session: AsyncSession, snapshot_id: uuid.UUID, claimed_at: datetime, usage: list[CallUsage]
) -> bool:
    """시도 기록을 `done` 으로 바꾼다 — 내 선점 시각 그대로일 때만. 모델 id 와 토큰은 사용량 기록과 같은 뜻이다."""
    attempt = ChatMemoryImpressionAttempt
    finished = await session.scalar(
        update(attempt)
        .where(attempt.snapshot_id == snapshot_id, attempt.status == "running", attempt.claimed_at == claimed_at)
        .values(status="done", finished_at=func.clock_timestamp(), **_usage_values(usage))
        .returning(attempt.snapshot_id)
    )
    return finished is not None


def _usage_values(usage: list[CallUsage]) -> dict[str, Any]:
    """이 시도의 사용량을 시도 기록에 **더하는** 값. 한 묶음 = 한 행이라 실패한 시도·다시 쥔 시도의 토큰이 같은 칸에 쌓인다
    (모델은 마지막 시도의 것). 보고되지 않은 칸은 건드리지 않는다."""
    if not usage:
        return {}
    attempt = ChatMemoryImpressionAttempt
    values: dict[str, Any] = {"model": usage[-1].model}
    for name in ("prompt_tokens", "cached_tokens", "output_tokens", "thoughts_tokens"):
        counts = [getattr(call, name) for call in usage]
        if all(count is None for count in counts):
            continue
        column = getattr(attempt, name)
        values[name] = func.coalesce(column, 0) + sum(count or 0 for count in counts)
    return values


async def _mark_failed(
    session_factory: async_sessionmaker[AsyncSession],
    snapshot_id: uuid.UUID,
    claimed_at: datetime,
    usage: list[CallUsage],
) -> None:
    """내 선점 그대로일 때만 `failed` 로 적는다 — 그사이 다른 작업이 다시 쥐었으면 그 작업의 기록을 건드리지 않는다. 응답을
    받고 나서 실패했으면 그 시도가 쓴 토큰도 더한다. 이 기록 자체가 실패하면 경고만 남긴다(10분 뒤 낡은 선점으로 다시 쥔다)."""
    attempt = ChatMemoryImpressionAttempt
    try:
        async with session_factory() as session:
            await session.execute(
                update(attempt)
                .where(
                    attempt.snapshot_id == snapshot_id, attempt.status == "running", attempt.claimed_at == claimed_at
                )
                .values(status="failed", **_usage_values(usage))
            )
            await session.commit()
    except Exception as exc:
        logger.warning("스냅샷 %s 인상 실패를 적지 못했다: %s", snapshot_id, exc)


async def _insert_impression(session: AsyncSession, row: ChatMemoryImpression) -> None:
    """행을 넣는다(커밋은 부르는 쪽). 따로 둔 것은 잠금 경합 테스트가 커밋 직전에 멈춰 세우는 자리여서다."""
    session.add(row)
    await session.flush()


def _sqlstate(exc: IntegrityError) -> str | None:
    """asyncpg 드라이버 오류의 SQLSTATE. SQLAlchemy 가 감싼 원래 오류(`exc.orig`)에 `sqlstate` 로 실린다."""
    state = getattr(exc.orig, "sqlstate", None)
    return state if isinstance(state, str) else None


def _dependency_tag(exc: Exception) -> str:
    """실패의 승격 태그 — 두 추출과 같은 규칙이다. 렌더 실패는 `prompt_render`, LLM 실패는 공급자와 쿼터 소진 여부로 가른 태그,
    DB 실패는 `db`, 그 밖은 `memory_impression`."""
    if isinstance(exc, PromptRenderError):
        return "prompt_render"
    if isinstance(exc, LLMClientError):
        return dependency_tag(exc)
    if isinstance(exc, SQLAlchemyError):
        return "db"
    return "memory_impression"
