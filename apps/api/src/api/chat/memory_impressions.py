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

입력 — 묶음 스냅샷의 장면·사실 행 중 아는 사람(`known_by`)이 정해지지 않은 것뿐이다. 요약 글·원문 대화·노트는 읽지 않는다. 비밀은
행의 칸 하나로 빠지므로 비밀 행이 있든 없든 프롬프트가 바이트까지 같다. 남는 위험: 추출이 비밀을 공개로 잘못 적은 행은 들어온다.

쓰기 — 잠금 순서는 두 추출과 같다. 입력을 읽기 전에 방의 잊기 세대를 읽어 두고, 마지막 트랜잭션에서 **먼저** 가장 새 스냅샷을
`FOR KEY SHARE` 로 잠근 뒤(없으면 되감겼다 — 끝) 세대를 다시 읽어 다르면 결과를 버린다(그사이 방 주인이 장면이나 사실을 잊게
했다 — 결과에 잊은 내용이 들어 있을 수 있다). 잊게 하기는 그 방 스냅샷을 전부 `FOR UPDATE` 로 잡고 그 방의 인상을 전부 지우므로,
이 잠금을 쥔 동안에는 끝나지 않고 커밋을 기다렸다가 방금 넣은 행까지 지운다(`chat/memory_forget.py`). 세대를 잠금 전에 다시 읽으면
그 사이에 커밋된 잊기를 놓친다. 인상 행은 여기서 지우지 않는다 — 되감기는 스냅샷 DELETE 의 CASCADE 가 지운다.

같은 묶음을 두 작업이 함께 만들면 스냅샷 유니크가 뒤의 것을 막는다(경합이라 실패로 세지 않는다). 실패한 묶음은 선점 기록 없이
다음 턴 뒤에 다시 본다 — 그 묶음이 가장 새 묶음인 동안(다음 접기 전까지)만."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
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
    ChatRoom,
    ChatRoomMemorySnapshot,
    PromptSection,
    PromptSet,
)
from api.db.models.chat import IMPRESSION_TEXT_MAX
from api.llm.chat_models import ChatModelId
from api.llm.client import LLMCallContext, LLMCallSite, LLMClient, LLMClientError, dependency_tag

logger = logging.getLogger(__name__)

_IMPRESSION_CALL_SITE: LLMCallSite = "chat_memory_impression"

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

    1. 범위 밖이면 끝.
    2. 새 세션에서 묶음을 고른다(모듈 설명 「언제 만드나」). 없으면 끝. 방의 잊기 세대를 읽은 **뒤에** 입력 행을 읽는다 — 그 뒤에
       커밋된 잊기를 4 에서 알아챈다. 입력 행이 하나도 없으면 부르지 않는다.
    3. 세션 없이 모델을 부른다. 글은 앞뒤 공백을 걷고 상한에서 자르며, 비면 쓰지 않는다.
    4. 새 세션 한 트랜잭션: 가장 새 스냅샷 `FOR KEY SHARE` → 세대 재확인(다르면 버림) → 행을 넣고 커밋. 외래 키·유니크 위반은
       경합이라 경고만 남긴다.
    5. 그 밖의 실패(렌더·모델·DB·예외)는 경고와 Bugsink 로 남긴다."""
    if not memory_model_in_scope(prompt_set.lane, writing_model, settings.memory_model_scope):
        return
    try:
        async with session_factory() as session:
            group = await _due_group(session, room_id, settings.memory_impression_every_n_folds)
            if group is None:
                return
            generation = await _forget_generation(session, room_id)
            episodes, facts = await _load_inputs(session, group)
        if not episodes and not facts:
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
            usage=LLMCallContext(call_site=_IMPRESSION_CALL_SITE, user_id=user_id, room_id=room_id),
        )
        text = result.impression.strip()[:IMPRESSION_TEXT_MAX].strip()
        if not text:
            logger.warning("스냅샷 %s 인상을 쓰지 않는다 — 모델이 빈 글을 냈다", group.anchor_id)
            return

        async with session_factory() as session:
            if not await _lock_snapshot(session, group.anchor_id):
                return
            if await _forget_generation(session, room_id) != generation:
                await session.rollback()
                logger.warning(
                    "스냅샷 %s 인상을 버린다 — 입력을 읽은 뒤 방 주인이 장면이나 사실을 잊게 했다", group.anchor_id
                )
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
    """묶음 스냅샷의 장면·사실 행 중 아는 사람이 정해지지 않은 것, 스냅샷 커서 순·그 안은 순번 순."""
    snapshot = ChatRoomMemorySnapshot
    order = (snapshot.cursor_created_at, snapshot.cursor_message_id)
    episodes = (
        await session.scalars(
            select(ChatMemoryEpisode)
            .join(snapshot, snapshot.id == ChatMemoryEpisode.snapshot_id)
            .where(ChatMemoryEpisode.snapshot_id.in_(group.snapshot_ids), ChatMemoryEpisode.known_by.is_(None))
            .order_by(*order, ChatMemoryEpisode.ordinal)
        )
    ).all()
    facts = (
        await session.scalars(
            select(ChatMemoryFact)
            .join(snapshot, snapshot.id == ChatMemoryFact.snapshot_id)
            .where(ChatMemoryFact.snapshot_id.in_(group.snapshot_ids), ChatMemoryFact.known_by.is_(None))
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
