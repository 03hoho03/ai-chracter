import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TypeVar

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.sse import EventSourceResponse
from redis.exceptions import RedisError
from sqlalchemy import and_, delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased
from starlette.concurrency import run_in_threadpool

from api.chat.chat_count import record_chat_participant
from api.chat.ending_rules import (
    EndingCandidate,
    ending_judgment_order,
    evaluate_rule_list,
    is_ending_check_due,
    referenced_stat_ids,
)
from api.chat.memory_fold import SUMMARY_MAX_LENGTH, fold_memory
from api.chat.memory_rewind import rewind_memory
from api.chat.memory_window import CurrentSummary, load_current_summary, prompt_window, select_current_snapshot
from api.chat.preview_session import create_preview_session, get_preview_session, update_preview_session
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    MediaCellCandidate,
    PromptLane,
    PromptNames,
    PromptRenderError,
    PromptSetNotFoundError,
    StatJudgmentRequest,
    StatRuleJudgmentResult,
    build_ending_judgment_prompt,
    build_image_judgment_prompt,
    load_active_prompt_set,
    media_cell_image_lines,
    prepare_stat_judgment,
    situational_image_lines,
)
from api.chat.prompt_set_cache import get_cached_active_prompt_set, set_cached_active_prompt_set
from api.chat.room_deletion import delete_chat_rooms
from api.chat.room_stats import load_room_stats, seed_missing_room_stats
from api.chat.turn_lock import (
    RoomTurnLock,
    acquire_room_turn_lock,
    hold_room_turn_lock,
    release_room_turn_lock,
)
from api.chat.turn_prompt import (
    build_preview_prompt,
    build_room_prompt,
    format_persona,
    generation_prompt_set,
    preview_ending_rule_list_item,
)
from api.chat.turn_settlement import TurnSettlement
from api.chat.schemas import (
    ChangeStartingSetupRequest,
    ChatDoneEvent,
    ChatEndingReachedEvent,
    ChatErrorEvent,
    ChatMessageCreateRequest,
    ChatMessageEditRequest,
    ChatMessagePageResponse,
    ChatMessageResponse,
    ChatModelItem,
    ChatPolicyWarningEvent,
    ChatRoomContentSnapshot,
    ChatRoomCreateRequest,
    ChatRoomListItem,
    ChatRoomMemoryLimits,
    ChatRoomMemoryNoteRequest,
    ChatRoomMemoryResponse,
    ChatRoomMemoryRevertRequest,
    ChatRoomMemorySummary,
    ChatRoomMemorySummaryRequest,
    ChatRoomModelResponse,
    ChatRoomModelSelectRequest,
    ChatRoomRenameRequest,
    ChatRoomResponse,
    ChatStatChangeEvent,
    ChatStreamEvent,
    ChatTokenEvent,
    EndingCollectionItem,
    EndingRuleGroupItem,
    EndingRuleItem,
    EndingRuleListItem,
    EndingSnapshot,
    ImageArchiveItem,
    MyChatRoomListItem,
    MEMORY_NOTE_MAX_LENGTH,
    PlayGuideResponse,
    PreviewSessionStartResponse,
    PreviewSessionState,
    ShortcutSnapshot,
    StatDefSnapshot,
    StoryImageArchiveItem,
)
from api.chat.stats import apply_rule_judgment
from api.content.access import detail_model_for, is_open_to, is_open_to_participant
from api.content.author_macros import expand_author_macros, resolve_user_name
from api.content.media_book import (
    normalize_texts,
    normalize_texts_for_display,
    resolve_media_tag_images,
    sign_owned_cell_images,
)
from api.content.media_tags import media_tag_refs, normalize_media_tags, strip_media_tags
from api.content.schemas import (
    CharacterDraftPayload,
    MediaTagImage,
    ShortcutDraftItem,
    StatDefDraftItem,
    StoryDraftPayload,
)
from api.core.config import settings
from api.core.rate_limit_gate import ChatCharge, charge_chat_turn, enforce_chat_rate_limit
from api.core.s3 import build_thumbnail_key, generate_presigned_get_url
from api.core.sentry import capture_dependency_failure
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.chat import (
    CharacterImageExposure,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomMemorySnapshot,
    ChatRoomStat,
    DiscardedResponse,
    StoryEndingUnlock,
    StoryMediaExposure,
)
from api.db.models.content import Content, ContentType, ModerationStatus
from api.db.models.media import Asset
from api.db.models.novel import Novel
from api.db.models.persona import UserPersona
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import (
    Ending,
    EndingRule,
    EndingRuleGroup,
    MediaBookCell,
    MediaBookPerson,
    MediaBookScene,
    Shortcut,
    StartingSetup,
    StatDef,
    StatRule,
    StoryVersionDetail,
)
from api.db.session import get_db_session, get_session_factory
from api.legal.dependencies import require_legal_consent
from api.llm.chat_models import CHAT_MODELS, DEFAULT_CHAT_MODEL, ChatModelId, actual_model_id, chat_turn_cost
from api.llm.client import (
    LLMCallContext,
    LLMClient,
    LLMClientError,
    LLMPolicyViolationError,
    dependency_tag,
)
from api.llm.dependencies import get_llm_client
from api.llm.model_access import effective_room_model, has_chat_premium_access
from api.persona.router import get_owned_persona, lock_user_default_persona
from api.persona.schemas import PersonaSelectRequest, RoomPersonaResponse
from api.session.dependencies import get_current_user_id

# LLM 실패(특히 429 쿼터 소진)는 화면에 "대화 품질 문제"와 구분되지 않게 보이므로 반드시
# 서버 로그에 남긴다. uvicorn은 root logger에 핸들러를 붙이지 않아 INFO는 조용히 사라지지만
# WARNING 이상은 logging.lastResort로 stderr에 찍힌다 — 이 모듈의 로그는 전부 warning 이상.
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat-rooms", tags=["chat"])

# `/stories/*`, `/characters/*`는 `/chat-rooms/*`와 같은 채팅 API에
# 속하지만 URL prefix가 달라 같은 파일 안에 별도 APIRouter를 둔다 (`api/auth/router.py`의
# `me_router`와 동일 패턴).
stories_router = APIRouter(prefix="/stories", tags=["chat"])
characters_router = APIRouter(prefix="/characters", tags=["chat"])
preview_router = APIRouter(prefix="/preview-sessions", tags=["chat"])
# `router`의 prefix가 `/chat-rooms`라 여기 얹으면 `/chat-rooms/me/...`가 되므로 별도 라우터가
# 필요하다 — 위 stories_router/characters_router와 동일 이유. `api.auth.router.me_router`가
# 이미 그 이름을 쓰므로 main.py에서 반드시 별칭으로 import한다.
me_router = APIRouter(prefix="/me", tags=["chat"])
# 채팅방에 고를 수 있는 글쓰기 모델 목록. prefix 가 달라 따로 둔다(위 라우터들과 같은 이유).
chat_models_router = APIRouter(prefix="/chat-models", tags=["chat"])


async def _get_owned_room(db: AsyncSession, room_id: uuid.UUID, user_id: uuid.UUID) -> ChatRoom:
    room = await db.get(ChatRoom, room_id)
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat room not found")
    if room.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the chat room owner")
    return room


async def _owned_room_dependency(
    room_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoom:
    """Same ownership check as `_get_owned_room`, but as a `Depends()` so it resolves
    (and can raise a clean 404/403) before an SSE route's generator body starts —
    an `HTTPException` raised *inside* that generator escapes FastAPI's normal
    exception handling instead of becoming a JSON error response."""
    return await _get_owned_room(db, room_id, user_id)


def _ensure_content_playable(content: Content) -> None:
    """이용제한·삭제된 작품에서는 모델을 부르거나 새 방을 만들지 않는다. 지난 대화 읽기·방 삭제·초기화는 막지
    않는다 — 초기화는 저장된 오프닝을 다시 넣을 뿐 모델을 부르지 않는다. 작가 본인의 실제 방도 같이 막고, 빌더
    미리보기는 작품 행을 보지 않아 이 검사 밖이다.

    403 을 고른 이유: 기다려도 풀리지 않는 거부라 429(게이트 계약)가 아니고, 같은 꼴의 dict-code 403 을 재동의
    게이트가 이미 쓴다. FE 는 정지 403 을 detail 문자열로만 가르므로 이 dict 403 이 세션을 비우지 않는다."""
    if content.moderation_status != ModerationStatus.NORMAL:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "CONTENT_RESTRICTED"})


async def _playable_room_dependency(
    room: ChatRoom = Depends(_owned_room_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoom:
    """모델을 부르는 세 경로(전송·재생성·편집)의 방 의존성. 소유권 검사 바로 뒤에서 작품 상태를 본다 — 차감
    게이트(`enforce_room_chat_charge`)보다 앞이라 막힌 작품에서는 분당 상한도 세지 않고, 클로버 확인 모달도 뜨지 않고,
    클로버도 깎이지 않는다. SSE 제너레이터 본문에서 raise 하면 깨진 스트림이 되므로 `Depends` 로 둔다."""
    content = await db.get(Content, room.content_id)
    assert content is not None
    _ensure_content_playable(content)
    return room


async def _room_turn_lock_dependency(
    room: ChatRoom = Depends(_playable_room_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> AsyncIterator[RoomTurnLock]:
    """턴 세 경로(전송·재생성·편집)의 방 락(`chat/turn_lock.py`). 같은 방에 진행 중인 턴이 있으면 409 로 거절한다.

    자리는 방 소유·작품 검사 **뒤**, 메시지·단축어 검증과 차감 게이트 **앞**이다. 소유 검사 뒤인 이유는 키가 방 id 라
    앞에 두면 남의 방 id 로 그 방을 잠가 막을 수 있어서다. 게이트 앞인 이유는 거절된 요청이 클로버도 분당 상한도 쓰지
    않게 하려는 것이다. 메시지 검증 앞인 이유는 재생성의 "마지막 메시지가 응답인가"·편집 대상 메시지를 락 아래에서
    읽어야 앞 턴이 끝나는 사이의 낡은 판단으로 시작하지 않아서다. 같은 이유로 잡은 직후 방 행을 다시 읽는다 — 방은 락
    전에 읽혔고, 앞 턴이 커밋하고 락을 푼 직후에 들어온 요청은 그 턴이 올린 `turn_count` 를 못 본 채 시작한다.

    해제는 두 자리다. 라우트 제너레이터가 스트림 끝(`finally`)에서 먼저 푼다 — FastAPI 는 이 의존성의 정리를 스트림과
    background(요약 접기, LLM 호출) 가 다 끝난 **뒤에** 돌리므로, 여기서만 풀면 접는 동안 다음 턴이 409 를 받는다.
    여기의 `finally` 는 그물이다: 뒤 의존성이 거절해(400·404·429) 본문이 아예 시작되지 않은 경우, 그리고 본문의 해제가
    끝까지 돌지 못한 경우(클라이언트가 끊어 스트림이 취소되는 중에 해제 `await` 가 다시 취소되는 경우 등 — 끊김 테스트에서는
    본문 해제가 끝까지 돌았지만 취소 중의 `await` 를 보장하는 장치는 없다). 해제는 소유자 토큰을 비교하므로 두 번 불려도 남의
    락을 지우지 않는다."""
    lock = await acquire_room_turn_lock(room.id)
    try:
        await db.refresh(room)
        yield lock
    finally:
        await release_room_turn_lock(lock)


async def enforce_room_chat_charge(
    # 락이 방보다 앞이다 — 같은 요청 안에서 두 의존성은 한 번씩만 해석되므로(요청 스코프 캐시) 여기서 받는 방은 락을
    # 잡은 직후 다시 읽은 그 객체다. 라우트 시그니처가 이 순서를 이미 지키지만, 게이트가 스스로 보장하게 둔다.
    _turn_lock: RoomTurnLock = Depends(_room_turn_lock_dependency),
    room: ChatRoom = Depends(_playable_room_dependency),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> ChatCharge:
    """턴 세 경로(전송·재생성·편집)의 차감 게이트. 방이 고른 모델을 지금 쓸 모델로 읽어(허용이 없거나 레지스트리에서 내린
    모델이면 Gemini) 그 모델의 가격으로 차감한다. 상한·차감 본문은 미리보기와 같은 `charge_chat_turn` 이다.

    영수증의 `model` 이 이 턴의 생성 모델이다 — 생성 쪽은 방을 다시 읽지 않는다. 이 게이트와 생성 사이에 방의 모델이
    바뀌어도(모델 지정 라우트는 턴 락을 잡지 않는다) 값을 낸 모델로 생성한다.

    라우트 시그니처의 맨 뒤에 둔다(`send_message` 의 같은 자리 주석) — 조회·검증이 실패한 요청은 차감하지 않는다."""
    model = await effective_room_model(db, user_id, room.chat_model)
    return await charge_chat_turn(user_id, db, session_factory, model=model, price=chat_turn_cost(model))


async def _validate_shortcut(
    payload: ChatMessageCreateRequest,
    room: ChatRoom = Depends(_owned_room_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> Shortcut | None:
    """단축어 검증도 `_owned_room_dependency`와 같은 이유로 SSE 제너레이터 밖의
    평범한 Depends로 분리한다 — 제너레이터 본문 안에서 HTTPException을 raise하면
    정상 404/403처럼 400도 JSON 응답이 아니라 깨진 스트림이 되어버린다."""
    if payload.shortcut_id is None:
        return None
    shortcut = await db.scalar(
        select(Shortcut).where(
            Shortcut.entity_id == payload.shortcut_id,
            Shortcut.content_version_id == room.content_version_id,
        )
    )
    if shortcut is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid shortcutId")
    return shortcut


async def _starting_setup_dependency(
    room: ChatRoom = Depends(_owned_room_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> StartingSetup | None:
    """레인 선택과 빌더 선택이 **같은 값**에서
    나오게 하는 단일 판별원. `room.starting_setup_entity_id is None`(조기 반환)이 아니라
    `_require_starting_setup`의 결과를 쓴다 — 그쪽이 더 엄격하고(행의 실재까지 보고, 불일치면
    `Depends` 단계에서 400을 던진다), `build_room_prompt`가
    어차피 그 행을 필요로 한다. fastapi의 `Depends` 캐시(콜러블 동일성 기준, `use_cache=True`)
    가 있어 한 요청 안에서 `_require_starting_setup`이 두 번 불리지 않는다 —
    `_active_prompt_set_dependency`도 이 의존성을 거친다."""
    return await _require_starting_setup(db, room)


def _lane_for_setup(setup: StartingSetup | None) -> PromptLane:
    return "story" if setup is not None else "character"


def _lane_for_preview_payload(payload: CharacterDraftPayload | StoryDraftPayload) -> PromptLane:
    return "story" if isinstance(payload, StoryDraftPayload) else "character"


async def _active_prompt_set_dependency(
    setup: StartingSetup | None = Depends(_starting_setup_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> tuple[PromptSet, list[PromptSection]]:
    """이 세트는 언제나 그 레인의 **Gemini 세트**다 — 판정·요약·그림 판정은 방의 글쓰기 모델과 무관하게 이 세트를
    읽는다(Claude 세트에는 그 채널이 없다).

    실제 채팅은 요청 스코프 `db` 세션을 이미 갖고 있으므로 그대로 재사용한다
    (미리보기의 `_preview_prompt_set_dependency`와 달리
    세션을 짧게 여닫을 이유가 없다). 레인은 `_starting_setup_dependency`가 넘겨준 `setup`
    으로 정한다 — 라우트 본문이 따로 판별하지 않는다. 캐시 히트면 `db`를 조회하지
    않고 그대로 반환한다. `PromptSetNotFoundError`가 여기서 나면 SSE
    제너레이터 본문이 시작되기 전이라 정상적인 에러 응답이 된다 — 이 예외는 캐싱하지
    않는다(negative caching 금지)."""
    lane = _lane_for_setup(setup)
    cached = await get_cached_active_prompt_set(lane, model="gemini")
    if cached is not None:
        return cached
    prompt_set, sections = await load_active_prompt_set(db, lane=lane, model="gemini")
    await set_cached_active_prompt_set(lane, prompt_set, sections, model="gemini")
    return prompt_set, sections


# `_preview_prompt_set_dependency`는 여기 두지 않는다 — `_owned_preview_session_dependency`
# (아래, 미리보기 섹션)에 의존하는데 그 함수는 파일 뒤쪽에 정의된다. `Depends(...)`가
# 함수 정의 시점에 평가되는 기본 인자값이라, 그 함수 정의보다 앞에 두면 `NameError`가
# 난다 — 그래서 미리보기 섹션(`_owned_preview_session_dependency` 바로 아래)에 둔다.


async def _room_siblings(db: AsyncSession, user_id: uuid.UUID, content_id: uuid.UUID) -> list[ChatRoom]:
    """All of this user's rooms for one content, oldest first — the creation order
    that "대화 N" auto-numbering is based on."""
    return list(
        (
            await db.scalars(
                select(ChatRoom)
                .where(ChatRoom.user_id == user_id, ChatRoom.content_id == content_id)
                .order_by(ChatRoom.created_at.asc(), ChatRoom.id.asc())
            )
        ).all()
    )


def _display_name(room: ChatRoom, ordinal: int) -> str:
    return room.name or f"대화 {ordinal}"


async def _resolve_starting_setup(db: AsyncSession, room: ChatRoom) -> StartingSetup | None:
    """Story chat rooms only. `room.starting_setup_entity_id` is the version-stable
    reference — resolve it back to the physical row belonging to the room's
    *pinned* `content_version_id` (not necessarily the content's current version)."""
    if room.starting_setup_entity_id is None:
        return None
    setup: StartingSetup | None = await db.scalar(
        select(StartingSetup).where(
            StartingSetup.content_version_id == room.content_version_id,
            StartingSetup.entity_id == room.starting_setup_entity_id,
        )
    )
    return setup


async def _require_starting_setup(db: AsyncSession, room: ChatRoom) -> StartingSetup | None:
    """`_resolve_starting_setup`의 상류에서 "행이 정말
    없어야 하는 경우"와 "불일치로 없는 경우"를 가른다. `starting_setup_entity_id is None`은
    캐릭터 방의 정상 신호이므로 그대로 `None`을 돌려준다 — 400은 `entity_id`가 있는데 그
    행이 방이 고정한 버전에서 사라졌을 때만 던진다. 세 호출부만 이걸 쓴다(`_to_response`는
    제외)."""
    setup = await _resolve_starting_setup(db, room)
    if setup is None and room.starting_setup_entity_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chat room's starting setup is missing from its pinned content version",
        )
    return setup


async def _seed_initial_stats(db: AsyncSession, room: ChatRoom, setup: StartingSetup) -> None:
    stat_defs = (await db.scalars(select(StatDef).where(StatDef.starting_setup_id == setup.id))).all()
    for stat_def in stat_defs:
        db.add(
            ChatRoomStat(
                chat_room_id=room.id, stat_entity_id=stat_def.entity_id, current_value=stat_def.initial_value
            )
        )
    await db.flush()


def _ending_rule_item(rule: EndingRule) -> EndingRuleItem:
    return EndingRuleItem(
        id=rule.entity_id,
        stat_id=rule.stat_def_entity_id,
        operator=rule.operator,
        threshold=float(rule.threshold),
        next_op=rule.next_op,
    )


async def _ending_rule_items(db: AsyncSession, ending: Ending) -> list[EndingRuleListItem]:
    """`ending_rules`(top-level)와 `ending_rule_groups`(1단계 중첩) 두 테이블을 하나의
    `order` 공유 시퀀스로 합쳐 재구성한다 — 엔딩 규칙 평가 엔진(`evaluate_rule_list`)과
    contentSnapshot 응답 양쪽이 이 결과를 그대로 재사용한다."""
    top_rules = (await db.scalars(select(EndingRule).where(EndingRule.ending_id == ending.id))).all()
    top_groups = (await db.scalars(select(EndingRuleGroup).where(EndingRuleGroup.ending_id == ending.id))).all()

    items: list[tuple[int, EndingRuleListItem]] = [(rule.order, _ending_rule_item(rule)) for rule in top_rules]
    for group in top_groups:
        nested = (
            await db.scalars(
                select(EndingRule).where(EndingRule.rule_group_id == group.id).order_by(EndingRule.order)
            )
        ).all()
        items.append(
            (
                group.order,
                EndingRuleGroupItem(
                    id=group.entity_id, rules=[_ending_rule_item(r) for r in nested], next_op=group.next_op
                ),
            )
        )
    items.sort(key=lambda pair: pair[0])
    return [item for _, item in items]


def _ending_rules_pass(
    rule_items: list[EndingRuleListItem], stats: dict[str, float], *, log_subject: str, ending_id: uuid.UUID
) -> bool:
    """실채팅·미리보기 엔딩 루프가 판정 모델 앞에서 부른다. 값이 없는 스탯을 가리키는 항목은 `evaluate_rule_list`
    가 거짓으로 보고, 여기서 어느 엔딩의 어느 스탯인지 경고로 남긴다 — 그 엔딩이 영영 안 열리는 이유를 찾을 단서다."""
    missing_stat_ids = referenced_stat_ids(rule_items) - stats.keys()
    if missing_stat_ids:
        logger.warning(
            "%s 엔딩 %s 의 규칙이 값이 없는 스탯 %s 을 가리킨다 — 그 항목은 거짓으로 본다",
            log_subject,
            ending_id,
            ", ".join(sorted(missing_stat_ids)),
        )
    return evaluate_rule_list(rule_items, stats)


_JudgedEndingT = TypeVar("_JudgedEndingT")


def _endings_to_judge(
    due: Sequence[tuple[_JudgedEndingT, uuid.UUID, uuid.UUID | None, list[EndingRuleListItem]]],
    stats: dict[str, float],
    *,
    log_subject: str,
) -> list[_JudgedEndingT]:
    """판정 차례인 엔딩(목록 순서, `(엔딩, entity_id, 우선 스탯, 규칙)`)에서 이번 턴에 판정 모델을 부를 엔딩과 그 순서.
    실채팅·미리보기 엔딩 루프가 함께 쓴다 — 호출부는 이 순서로 판정하다 처음 발동한 엔딩에서 멈추고, 끝까지 발동이
    없으면 그 턴은 엔딩 없이 끝난다(우선 스탯 무리가 선 턴은 무리 1등까지만 판정한다).

    규칙을 먼저 전부 본 뒤 순서를 정한다(`ending_judgment_order`). 규칙은 이번 턴 반영 뒤 스탯만으로 정해지고 발동은
    규칙과 판정의 논리곱이라, 판정 모델 앞에서 미리 봐도 결과는 같고 규칙이 거짓인 엔딩의 호출만 준다. 우선 스탯 값이
    없어 무리에서 빠진 엔딩은 경고로 남긴다 — 무리 비교에서 빠진 이유를 찾을 단서다."""
    candidates = [
        EndingCandidate(ending=ending, ending_id=ending_id, priority_stat_id=priority_stat_id)
        for ending, ending_id, priority_stat_id, rule_items in due
        if _ending_rules_pass(rule_items, stats, log_subject=log_subject, ending_id=ending_id)
    ]
    order = ending_judgment_order(candidates, stats)
    for candidate in order.missing_priority:
        logger.warning(
            "%s 엔딩 %s 의 우선 스탯 %s 에 값이 없다 — 우선 스탯 비교에서 빼고 우선 스탯이 없는 엔딩처럼 다룬다",
            log_subject,
            candidate.ending_id,
            candidate.priority_stat_id,
        )
    return order.endings


@dataclass(frozen=True)
class _DueEndings:
    """이번 턴 엔딩 판정의 DB 읽기 결과 — 판정할 때가 된 엔딩(목록 순서)과 그 스탯 규칙, 판정 프롬프트에 실을
    히스토리·요약."""

    endings: list[tuple[Ending, list[EndingRuleListItem]]]
    history: list[ChatMessage]
    summary: str


async def _load_due_endings(
    db: AsyncSession, room: ChatRoom, setup: StartingSetup, history: list[ChatMessage], turn: int
) -> _DueEndings:
    """엔딩 판정에 필요한 것을 판정 LLM **앞에서** 읽는다 — 엔딩 판정은 엔딩마다 LLM 을 차례로 부르므로, 규칙을
    루프 안에서 읽으면 DB 읽기와 LLM 대기가 번갈아 트랜잭션을 쥔 채 LLM 을 기다린다. 판정할 때가 아닌 엔딩의 규칙은
    읽지 않는다(때는 이번 턴 번호와 엔딩의 게이트만으로 정해진다).

    판정 윈도우를 켜면 요약이 덮은 원문을 빼고 그 자리에 현재 요약을 싣는다 — 엔딩은 지금까지의 대화 전체를 보는 누적
    판단이라 원문만 줄이면 앞부분을 잃는다. 끄면 전체 히스토리 그대로다."""
    endings = list(
        (await db.scalars(select(Ending).where(Ending.starting_setup_id == setup.id).order_by(Ending.order))).all()
    )
    due = [
        (ending, await _ending_rule_items(db, ending))
        for ending in endings
        if is_ending_check_due(turn, ending.turn_count_gate)
    ]
    ending_history = history
    ending_summary = ""
    if settings.memory_window_generation and settings.memory_window_ending_judgment:
        current_summary = await load_current_summary(db, room.id)
        if current_summary is not None:
            ending_history = prompt_window(history, current_summary.cursor)
            ending_summary = current_summary.text
    return _DueEndings(endings=due, history=ending_history, summary=ending_summary)


def _write_room_stat(
    db: AsyncSession, room_id: uuid.UUID, stat_rows: dict[str, ChatRoomStat], stat_id: str, value: float
) -> None:
    """버전을 옮긴 방에는 새 버전에 생긴 스탯의 행이 없을 수 있다. 바뀐 값을 쓸 행이 없으면 만들어 쓴다."""
    row = stat_rows.get(stat_id)
    if row is None:
        row = ChatRoomStat(chat_room_id=room_id, stat_entity_id=uuid.UUID(stat_id), current_value=Decimal(str(value)))
        db.add(row)
        stat_rows[stat_id] = row
    else:
        row.current_value = Decimal(str(value))


async def _ending_snapshot(db: AsyncSession, ending: Ending) -> EndingSnapshot:
    """스냅숏은 아직 도달하지 않은 엔딩까지 싣는다. 그래서 에필로그의 미디어 북 태그는 그림으로 해석하지
    않고 지운다 — 해석하면 플레이어가 보지 못한 칸의 원본 URL 이 응답에 실린다. 화면은 에필로그를
    엔딩 이벤트·엔딩 모음에서 그리므로 여기서 태그가 사라져도 보이는 것이 없다."""
    return EndingSnapshot(
        id=ending.entity_id,
        name=ending.name,
        turn_count_gate=ending.turn_count_gate,
        judgment_prompt=ending.judgment_prompt,
        epilogue=strip_media_tags(ending.epilogue) if ending.epilogue is not None else None,
        hint=ending.hint,
        stat_rules=await _ending_rule_items(db, ending),
    )


async def _build_content_snapshot(
    db: AsyncSession, room: ChatRoom, setup: StartingSetup
) -> ChatRoomContentSnapshot:
    """stats/endings는 방이 고정한 시작설정(setup) 기준,
    단축어는 작품 전역(content_version_id) 기준."""
    stat_defs = (
        await db.scalars(
            select(StatDef).where(StatDef.starting_setup_id == setup.id).order_by(StatDef.order)
        )
    ).all()
    endings = (
        await db.scalars(
            select(Ending).where(Ending.starting_setup_id == setup.id).order_by(Ending.order)
        )
    ).all()
    shortcuts = (
        await db.scalars(select(Shortcut).where(Shortcut.content_version_id == room.content_version_id))
    ).all()

    return ChatRoomContentSnapshot(
        stats=[
            StatDefSnapshot(
                id=s.entity_id,
                name=s.name,
                icon=s.icon,
                color=s.color,
                min_value=s.min_value,
                max_value=s.max_value,
                initial_value=s.initial_value,
                unit=s.unit,
                description=s.description,
            )
            for s in stat_defs
        ],
        endings=[await _ending_snapshot(db, ending) for ending in endings],
        shortcuts=[
            ShortcutSnapshot(id=sc.entity_id, name=sc.name, description=sc.description, prompt=sc.prompt)
            for sc in shortcuts
        ],
        suggested_replies=setup.suggested_replies or [],
        pinned_starting_setup_id=setup.id,
    )


async def _load_situational_candidates(
    db: AsyncSession, room: ChatRoom
) -> tuple[list[SituationalImage], CurrentSummary | None]:
    """캐릭터 상황별 이미지 판정의 DB 읽기 — 후보 이미지(order 순)와, 판정 윈도우를 켰으면 현재 요약.

    조회 실패(`SQLAlchemyError`)는 여기서 흡수하고 후보 없음으로 돌려준다 — 호출부의
    `except (LLMClientError, PromptRenderError)` 는 DB 예외를 잡지 않아 그대로 두면 제너레이터를 뚫는다.

    `db.begin_nested()`(SAVEPOINT)로 국소화한다 — SAVEPOINT 없이 여기서 진짜 Postgres 실행 오류(`DBAPIError` 계열)가
    나면 트랜잭션이 aborted 상태가 되고, 이 `except`가 예외를 삼켜도 같은 트랜잭션에서 이어지는 문장은 전부
    `DBAPIError`로 부딪힌다 — 이 함수가 막으려는 파열이 한 자리 뒤로 미뤄질 뿐이다. 지금 호출부는 이 읽기 뒤에
    판정 앞 반납 커밋을 하고(aborted 트랜잭션의 커밋은 오류 없이 롤백으로 끝난다) 쓰기는 새 트랜잭션에서 하지만,
    가드가 그 커밋 위치에 기대지 않게 한다(테스트의 요청 세션은 바깥 트랜잭션에 묶여 그 커밋이 트랜잭션을 끝내지
    못하므로 실제 SQL 실패 테스트가 이 SAVEPOINT 를 직접 잰다). SAVEPOINT로 감싸면 실패가 그 SAVEPOINT에만
    갇히고 바깥 트랜잭션은 그대로 유효하게 남는다(SQLAlchemy 2.0.51 `AsyncSessionTransaction.__aexit__`이 예외 시
    SAVEPOINT까지만 rollback하고 재전파함을 소스로 확인, 격리 재현으로 실측 검증도 마쳤다)."""
    try:
        async with db.begin_nested():
            situational_images = list(
                (
                    await db.scalars(
                        select(SituationalImage)
                        .where(
                            SituationalImage.content_version_id == room.content_version_id,
                            # `PATCH /contents/{id}/draft`가
                            # 이미지 파일 업로드 전에 image_asset_id=NULL인 행을 먼저 만들 수 있다
                            # (character.py의 SituationalImage docstring). 지금은 발행 검증이 그런
                            # 행을 거부하지만, 그 검증이 생기기 전에 발행된 버전에는 NULL 행이 남아
                            # 있을 수 있다. 그런 후보를 판단 프롬프트에
                            # 싣지 않는다 — LLM이 존재하지 않는 이미지를 매칭할 원인을 여기서 끊는다.
                            SituationalImage.image_asset_id.is_not(None),
                        )
                        .order_by(SituationalImage.order)
                    )
                ).all()
            )
            current_summary = await _image_judgment_summary(db, room) if situational_images else None
    except SQLAlchemyError as exc:
        logger.warning("대화방 %s 상황이미지 후보 조회 실패 — 이번 턴은 매칭을 건너뛴다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency="db")
        return [], None
    return situational_images, current_summary


async def _image_judgment_summary(db: AsyncSession, room: ChatRoom) -> CurrentSummary | None:
    """판정 윈도우를 켜면 요약이 덮은 원문을 뺀다 — 장면 매칭은 최근 원문이면 충분해 요약은 싣지 않는다.
    캐릭터 상황별 이미지와 스토리 칸 판정이 같은 스위치를 따른다. 후보가 있을 때만 부른다."""
    if settings.memory_window_generation and settings.memory_window_image_judgment:
        return await load_current_summary(db, room.id)
    return None


async def _judge_image_entity(
    llm_client: LLMClient, prompt: str, candidate_ids: set[uuid.UUID], usage: LLMCallContext
) -> uuid.UUID | None:
    """그림 고르기 판정 LLM 호출 — DB 에 닿지 않는다(스토리 턴은 이것만 스탯 판정과 동시에 부른다). 응답
    id 가 후보 안에 있을 때만 돌려준다: 응답은 문자열이라 형식이 틀리거나 후보 밖(노출 제외 칸 등)일 수 있다.
    `LLMClientError` 는 그대로 올린다 — 흡수 범위는 호출부가 정한다."""
    judgment = await llm_client.generate_structured(prompt, ImageMatchJudgmentResult, usage=usage)
    return next(
        (entity_id for entity_id in candidate_ids if str(entity_id) == judgment.matched_image_entity_id), None
    )


async def _record_character_image_exposure(db: AsyncSession, room: ChatRoom, image_entity_id: uuid.UUID) -> bool:
    """첫 노출만 기록한다(멱등). 실패는 SAVEPOINT 안에 가두고 `False` — 그 턴은 이미지를 붙이지 않는다(판정은
    성공했는데 노출 기록만 실패한 경우도 매칭을 절반만 살려두지 않는다)."""
    try:
        async with db.begin_nested():
            existing_exposure = await db.scalar(
                select(CharacterImageExposure).where(
                    CharacterImageExposure.user_id == room.user_id,
                    CharacterImageExposure.content_id == room.content_id,
                    CharacterImageExposure.image_entity_id == image_entity_id,
                )
            )
            if existing_exposure is None:
                db.add(
                    CharacterImageExposure(
                        user_id=room.user_id,
                        content_id=room.content_id,
                        image_entity_id=image_entity_id,
                    )
                )
    except SQLAlchemyError as exc:
        logger.warning("대화방 %s 이미지 노출 기록 실패 — 이번 턴은 매칭을 건너뛴다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency="db")
        return False
    return True


@dataclass(frozen=True)
class _SituationalImageJudgment:
    """캐릭터 상황별 이미지 판정 한 번에 필요한 것 — DB 읽기·프롬프트 조립을 끝낸 상태라 LLM 호출만 남았다."""

    prompt: str
    candidates: list[SituationalImage]


async def _prepare_situational_image_judgment(
    db: AsyncSession,
    room: ChatRoom,
    *,
    prompt_set: PromptSet,
    prompt_sections: list[PromptSection],
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
    names: PromptNames,
) -> _SituationalImageJudgment | None:
    """캐릭터 챗 상황별 이미지 판정의 DB 읽기와 프롬프트 조립. 등록된 이미지가 없으면 `None` — 판정 호출 자체를
    생략한다. 판정(`_judge_situational_image`)과 노출 기록(`_record_character_image_exposure`)을 따로 두는 이유는 그
    사이에 요청 세션을 커밋으로 반납하기 위해서다 — 판정 LLM 을 기다리는 동안 커넥션을 쥐지 않는다.

    조회 실패는 `_load_situational_candidates` 가 흡수한다. 렌더 실패(`PromptRenderError`)는 호출부가 흡수한다."""
    situational_images, current_summary = await _load_situational_candidates(db, room)
    if not situational_images:
        return None
    if current_summary is not None:
        history = prompt_window(history, current_summary.cursor)

    prompt = build_image_judgment_prompt(
        prompt_set=prompt_set,
        sections=prompt_sections,
        scope="character",
        assistant_label=prompt_set.character_assistant_label,
        image_lines=situational_image_lines(situational_images, names=names),
        history=history,
        user_message=user_message,
        assistant_message=assistant_message,
        names=names,
    )
    return _SituationalImageJudgment(prompt=prompt, candidates=situational_images)


async def _judge_situational_image(
    llm_client: LLMClient, judgment: _SituationalImageJudgment, room: ChatRoom
) -> SituationalImage | None:
    """상황별 이미지 판정 LLM 호출 — DB 에 닿지 않는다. 응답(matchedImageEntityId)은 항상 단수라 "동시 매칭 시
    order 최상위만 발동"은 프롬프트 지시로 처리하고, 그 반환값이 실제 후보 목록에 있는지만 방어적으로 재확인한다.
    매칭된 이미지 자체(entity_id 뿐 아니라 image_asset_id 도 필요, 인라인 렌더링 URL 조회용)를 돌려준다.
    `LLMClientError` 는 그대로 올린다 — 흡수 범위는 호출부가 정한다."""
    matched_id = await _judge_image_entity(
        llm_client,
        judgment.prompt,
        {image.entity_id for image in judgment.candidates},
        LLMCallContext(call_site="chat_situational_image", user_id=room.user_id, room_id=room.id),
    )
    return next((image for image in judgment.candidates if image.entity_id == matched_id), None)


@dataclass(frozen=True)
class _MediaCellJudgment:
    """스토리 칸 판정 한 번에 필요한 것 — DB 읽기·프롬프트 조립을 끝낸 상태라 LLM 호출만 남았다."""

    prompt: str
    candidate_ids: set[uuid.UUID]


async def _prepare_media_cell_judgment(
    db: AsyncSession,
    room: ChatRoom,
    *,
    prompt_set: PromptSet,
    prompt_sections: list[PromptSection],
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
    names: PromptNames,
) -> _MediaCellJudgment | None:
    """스토리 미디어 북 칸 판정의 DB 읽기와 프롬프트 조립. 후보는 방이 고정한 버전의 칸 중 대화 중 노출
    제외가 아닌 것이고, 빌더 축 순서(인물 → 장면)로 싣는다. 후보가 없으면(미디어 북 없음·전부 노출 제외)
    `None` — 판정을 부르지 않는다.

    판정 쪽 실패는 전부 여기서 흡수하고 `None` 이다 — 조회 실패는 캐릭터 후보 조회와 같은 SAVEPOINT 규칙,
    렌더 실패(배포 직후 캐시에 남은 옛 세트의 빈 프롬프트 포함)는 그 턴의 그림만 포기한다. 스탯·엔딩 판정은
    이 실패와 무관하게 돈다."""
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(
                        MediaBookCell.entity_id,
                        MediaBookPerson.name,
                        MediaBookScene.name,
                        MediaBookCell.situation_description,
                    )
                    .select_from(MediaBookCell)
                    .join(
                        MediaBookPerson,
                        and_(
                            MediaBookPerson.content_version_id == MediaBookCell.content_version_id,
                            MediaBookPerson.entity_id == MediaBookCell.person_entity_id,
                        ),
                    )
                    .join(
                        MediaBookScene,
                        and_(
                            MediaBookScene.content_version_id == MediaBookCell.content_version_id,
                            MediaBookScene.entity_id == MediaBookCell.scene_entity_id,
                        ),
                    )
                    .where(
                        MediaBookCell.content_version_id == room.content_version_id,
                        MediaBookCell.exclude_from_chat.is_(False),
                    )
                    .order_by(MediaBookPerson.order, MediaBookScene.order)
                )
            ).tuples().all()
            candidates = [
                MediaCellCandidate(entity_id=cell_id, person=person, scene=scene, situation_description=situation)
                for cell_id, person, scene, situation in rows
            ]
            current_summary = await _image_judgment_summary(db, room) if candidates else None
    except SQLAlchemyError as exc:
        logger.warning("대화방 %s 미디어 북 칸 후보 조회 실패 — 이번 턴은 칸 판정을 건너뛴다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency="db")
        return None
    if not candidates:
        return None
    if current_summary is not None:
        history = prompt_window(history, current_summary.cursor)
    try:
        prompt = build_image_judgment_prompt(
            prompt_set=prompt_set,
            sections=prompt_sections,
            scope="story",
            assistant_label=prompt_set.story_assistant_label,
            image_lines=media_cell_image_lines(candidates, names=names),
            history=history,
            user_message=user_message,
            assistant_message=assistant_message,
            names=names,
        )
    except PromptRenderError as exc:
        logger.warning("대화방 %s 미디어 북 칸 판정 프롬프트 렌더 실패 — 이번 턴은 그림 없이 진행한다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        return None
    return _MediaCellJudgment(prompt=prompt, candidate_ids={cell.entity_id for cell in candidates})


async def _judge_media_cell(
    llm_client: LLMClient, judgment: _MediaCellJudgment, usage: LLMCallContext, *, log_subject: str
) -> uuid.UUID | None:
    """스토리 칸 판정 LLM 호출. 실패(`LLMClientError`)는 여기서 흡수해 그림만 포기한다 — 스탯 판정과 동시에
    돌 때 한쪽 예외가 다른 쪽 결과를 지우지 않게 한다. DB 에 닿지 않는다."""
    try:
        return await _judge_image_entity(llm_client, judgment.prompt, judgment.candidate_ids, usage)
    except LLMClientError as exc:
        logger.warning("%s 미디어 북 칸 판정 실패 — 이번 턴은 그림 없이 진행한다: %s", log_subject, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        return None


async def _record_story_media_exposure(db: AsyncSession, room: ChatRoom, cell_entity_id: uuid.UUID) -> bool:
    """보관함 해금 기록 — 사용자·스토리별로 처음 본 칸만 남는다(멱등, 겹친 두 턴도 복합 PK 충돌 없이). 실패는
    SAVEPOINT 안에 가두고 `False` — 그 턴은 칸을 붙이지 않는다(캐릭터 노출 기록과 같은 규칙)."""
    try:
        async with db.begin_nested():
            await db.execute(
                pg_insert(StoryMediaExposure)
                .values(user_id=room.user_id, content_id=room.content_id, cell_entity_id=cell_entity_id)
                .on_conflict_do_nothing()
            )
    except SQLAlchemyError as exc:
        logger.warning("대화방 %s 미디어 북 칸 노출 기록 실패 — 이번 턴은 그림 없이 진행한다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency="db")
        return False
    return True


async def _record_story_media_unlocks(db: AsyncSession, room: ChatRoom, cell_entity_ids: set[uuid.UUID]) -> None:
    """첫 메시지·에필로그에 나온 칸의 보관함 해금 기록. 메시지와 같은 트랜잭션에 쓰고, 이미 본 칸과 겹치면 그대로
    둔다(대화 초기화가 같은 첫 메시지를 다시 넣어도 실패하지 않는다)."""
    if not cell_entity_ids:
        return
    await db.execute(
        pg_insert(StoryMediaExposure)
        .values(
            [
                {"user_id": room.user_id, "content_id": room.content_id, "cell_entity_id": cell_entity_id}
                for cell_entity_id in cell_entity_ids
            ]
        )
        .on_conflict_do_nothing()
    )


async def _unlock_epilogue_cells(db: AsyncSession, room: ChatRoom, epilogue: str | None) -> None:
    """도달한 엔딩의 에필로그에 나온 칸을 해금한다. 스트림 본문에서 불리므로 실패는 SAVEPOINT 안에 가두고 기록만
    포기한다 — 엔딩 도달 자체는 그대로 남는다."""
    if not epilogue:
        return
    # SAVEPOINT 를 열면 세션이 먼저 flush 된다. 그때 터지는 것은 바로 앞의 엔딩 도달 기록이지 칸 해금이 아니다 —
    # 여기서 따로 flush 해 그 실패가 아래 경고로 잘못 기록되지 않게 한다(이 실패는 전처럼 커밋 실패와 같은 길을 간다).
    await db.flush()
    try:
        async with db.begin_nested():
            _, refs = await normalize_texts(db, room.content_version_id, [epilogue])
            await _record_story_media_unlocks(db, room, refs)
    except SQLAlchemyError as exc:
        logger.warning("대화방 %s 에필로그 칸 해금 기록 실패 — 엔딩은 그대로 진행한다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency="db")


async def _sign_judged_cell(db: AsyncSession, room: ChatRoom, cell_entity_id: uuid.UUID) -> MediaTagImage | None:
    """커밋 뒤 판정 칸의 그림을 서명한다(원본, 너비·높이). 방 버전에서 칸·자산을 못 찾거나 서명이 실패하면
    `None` — 커밋 뒤라 예외가 새면 SSE 제너레이터를 뚫으므로 전부 흡수하고 그림 없이 마무리한다.
    `fold_memory` 예약 **앞**에서 부른다(예약 뒤에는 요청 세션 쿼리를 더하지 않는다)."""
    try:
        images = await resolve_media_tag_images(db, room.content_version_id, [cell_entity_id])
    except Exception as exc:
        logger.warning("대화방 %s 미디어 북 칸 URL 조립 실패 — 그림 없이 진행한다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency="s3")
        return None
    return images.get(cell_entity_id)


async def _await_stat_judgment(
    llm_client: LLMClient,
    request: StatJudgmentRequest,
    usage: LLMCallContext,
    *,
    log_subject: str,
    current_stats: dict[str, float],
    stat_defs: list[StatDef],
) -> dict[str, float] | None:
    """스탯 판정 LLM 호출과 반영. 반영한 스탯 값(키 → 값, 바뀌지 않은 스탯 포함)을 돌려준다. 판정 LLM 이 고른 규칙을
    `apply_rule_judgment` 로 반영한다. 요청에 프롬프트가 없으면(`prepare_stat_judgment` 가 판정할 규칙이 없다고 정했다)
    LLM 을 부르지 않고 발동 규칙 없이 반영한다 — 카운터는 굴러가고, 결과가 `None` 이 아니라 엔딩 판정도 이어진다.

    LLM 실패는 흡수해 `None` — 칸 판정과 동시에 돌 때 이 실패가 칸 결과를 지우지 않게 한다. `None` 이면 호출부는 지금처럼
    스탯·엔딩 판정을 함께 건너뛴다."""
    if request.prompt is None:
        return apply_rule_judgment(current_stats, [], request.rule_ids, stat_defs)
    try:
        rule_judgment = await llm_client.generate_structured(request.prompt, StatRuleJudgmentResult, usage=usage)
        return apply_rule_judgment(current_stats, rule_judgment.fired_rule_ids, request.rule_ids, stat_defs)
    except LLMClientError as exc:
        logger.warning("%s 스탯 판정 실패 — 이번 턴의 스탯·엔딩 판정을 건너뛴다: %s", log_subject, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        return None


async def _load_stat_rules(db: AsyncSession, stat_defs: Sequence[StatDef]) -> dict[uuid.UUID, list[StatRule]]:
    """스탯들의 규칙을 스탯 entity_id → 규칙 목록(`order` 순)으로 읽는다. 규칙은 스탯을 물리 FK 로 가리키므로 방이 고정한
    버전의 스탯 행에 달린 규칙만 나온다."""
    entity_id_by_stat_def_id = {stat_def.id: stat_def.entity_id for stat_def in stat_defs}
    rules_by_stat_id: dict[uuid.UUID, list[StatRule]] = {}
    for rule in (
        await db.scalars(
            select(StatRule)
            .where(StatRule.stat_def_id.in_(list(entity_id_by_stat_def_id)))
            .order_by(StatRule.order)
        )
    ).all():
        rules_by_stat_id.setdefault(entity_id_by_stat_def_id[rule.stat_def_id], []).append(rule)
    return rules_by_stat_id


async def _no_judgment() -> None:
    return None


def _turn_message_response(
    message: ChatMessage,
    matched_image: SituationalImage | None,
    matched_image_url: str | None,
    judged_cell_id: uuid.UUID | None,
    judged_cell_image: MediaTagImage | None,
) -> ChatMessageResponse:
    """턴(새 턴·재생성)의 `done.finalMessage`. 스토리 칸은 원본 비율로 그리게 너비·높이를 싣고, 캐릭터 상황별
    이미지는 싣지 않는다(지금의 고정 비율 칸 그대로). 칸 그림을 서명하지 못했으면 이미지 없이 보낸다 —
    상황별 이미지 URL 조립 실패와 같은 규칙이다."""
    if judged_cell_id is not None and judged_cell_image is not None:
        return ChatMessageResponse(
            id=message.id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            image_id=judged_cell_id,
            image_url=judged_cell_image.url,
            image_width=judged_cell_image.width,
            image_height=judged_cell_image.height,
        )
    return ChatMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        image_id=matched_image.entity_id if matched_image is not None else None,
        image_url=matched_image_url,
    )


async def _insert_opening_message(db: AsyncSession, room: ChatRoom, setup: StartingSetup | None) -> ChatMessage:
    """방의 첫 assistant 메시지를 넣는다. 방 생성·시작설정 변경(`_create_room`)과 대화 초기화
    (`reset_chat_room`)가 모두 이 함수를 지난다.

    스토리면 작성자 글의 미디어 북 태그를 방이 고정한 버전의 칸 id 형태로 바꿔 저장한다(없는 이름은
    지운다). 이름이 아니라 버전이 바뀌어도 유지되는 칸 id 로 두어야, 방이 새 발행본으로 옮겨 갔을 때 같은
    칸의 새 그림으로 해석되고 지워진 칸은 빈칸이 된다. 첫 메시지에 나온 칸은 보관함에서 해금한다 — 세 호출부가
    모두 이 함수를 지나야 초기화도 같은 기록을 남긴다."""
    if setup is not None:
        [opening_text], opening_refs = await normalize_texts(
            db, room.content_version_id, [setup.opening_message or setup.prologue]
        )
        await _record_story_media_unlocks(db, room, opening_refs)
    else:
        detail = await db.get(CharacterVersionDetail, room.content_version_id)
        assert detail is not None
        opening_text = detail.intro
    message = ChatMessage(chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content=opening_text)
    db.add(message)
    await db.flush()
    return message


async def _load_message_page(
    db: AsyncSession, room_id: uuid.UUID, *, before: ChatMessage | None, limit: int | None
) -> tuple[Sequence[ChatMessage], bool]:
    """방 메시지를 오래된 것부터 돌려주고, 그 앞에 더 있는지를 함께 알린다. `before` 가 있으면 그 메시지보다 앞의
    것만, `limit` 이 있으면 그중 최신 `limit` 개만. 정렬과 커서는 다른 모든 메시지 읽기와 같은 `(created_at, id)`
    다 — 한 트랜잭션에 넣은 메시지처럼 `created_at` 이 같아도 페이지 경계에서 빠지거나 겹치지 않는다. 더 있는지는
    하나 더 읽어 본다(개수 쿼리를 따로 부르지 않는다)."""
    query = select(ChatMessage).where(ChatMessage.chat_room_id == room_id)
    if before is not None:
        query = query.where(tuple_(ChatMessage.created_at, ChatMessage.id) < (before.created_at, before.id))
    if limit is None:
        messages = (
            await db.scalars(query.order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc()))
        ).all()
        return messages, False
    newest_first = (
        await db.scalars(query.order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(limit + 1))
    ).all()
    return list(reversed(newest_first[:limit])), len(newest_first) > limit


async def _sign_message_images(
    db: AsyncSession, room: ChatRoom, setup: StartingSetup | None, messages: Sequence[ChatMessage]
) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, MediaTagImage]]:
    """메시지에 실린 그림(`image_id`)의 URL 을 서명한다. 방 응답과 위로 불러오기 페이지가 같이 쓴다 — 한쪽만
    서명하면 그쪽 메시지의 그림이 URL 없이 온다."""
    # 이미지가 실린 메시지들의 entity_id를 모아
    # SituationalImage·Asset을 각 1회만 조회하고 서명한다 — 메시지마다 db.get을 부르면
    # 메시지 수만큼 쿼리가 늘어난다(N+1). image_id는 있는데 해석이 안 되면(SituationalImage
    # 없음/image_asset_id None/Asset 없음) image_url만 None으로 두고 image_id는 그대로 둔다.
    image_entity_ids = {m.image_id for m in messages if m.image_id is not None}
    image_urls: dict[uuid.UUID, str] = {}
    # 스토리 메시지의 image_id 는 미디어 북 칸이다 — 방이 고정한 버전의 칸으로 해석하고, 원본 비율로 그리게
    # 크기도 싣는다(캐릭터 상황별 이미지는 크기를 싣지 않는다). 방이 새 버전으로 옮겨 가면 같은 칸의 새 그림,
    # 지워진 칸이면 URL 없이 id 만 남는다.
    cell_images: dict[uuid.UUID, MediaTagImage] = {}
    if image_entity_ids and setup is not None:
        cell_images = await resolve_media_tag_images(db, room.content_version_id, image_entity_ids)
    elif image_entity_ids:
        situational_images = (
            await db.scalars(
                select(SituationalImage).where(
                    SituationalImage.content_version_id == room.content_version_id,
                    SituationalImage.entity_id.in_(image_entity_ids),
                )
            )
        ).all()
        asset_ids = {si.image_asset_id for si in situational_images if si.image_asset_id is not None}
        assets_by_id = {}
        if asset_ids:
            assets = (await db.scalars(select(Asset).where(Asset.id.in_(asset_ids)))).all()
            assets_by_id = {asset.id: asset for asset in assets}
        for si in situational_images:
            asset = assets_by_id.get(si.image_asset_id) if si.image_asset_id is not None else None
            if asset is None:
                continue
            image_urls[si.entity_id] = await run_in_threadpool(generate_presigned_get_url, asset.storage_key)

    return image_urls, cell_images


async def _to_response(db: AsyncSession, room: ChatRoom, *, message_limit: int | None = None) -> ChatRoomResponse:
    """방 응답. `message_limit` 가 있으면 메시지는 최신 그만큼만(오래된 것부터) 싣고 그 앞이 더 있는지를
    `has_more_messages_before` 로 알린다 — 긴 방의 진입 응답을 줄이려고 화면이 꼬리만 받고 위로 올라갈 때
    `GET /chat-rooms/{id}/messages?before=` 로 이어 받는다. 없으면 전부다(파라미터를 모르는 화면과 호환)."""
    content = await db.get(Content, room.content_id)
    assert content is not None
    version_detail: CharacterVersionDetail | StoryVersionDetail | None = (
        await db.get(CharacterVersionDetail, room.content_version_id)
        if content.type == ContentType.CHARACTER
        else await db.get(StoryVersionDetail, room.content_version_id)
    )
    assert version_detail is not None
    persona = await db.get(UserPersona, room.persona_id) if room.persona_id is not None else None

    siblings = await _room_siblings(db, room.user_id, room.content_id)
    ordinal = next(index for index, sibling in enumerate(siblings, start=1) if sibling.id == room.id)

    messages, has_more_before = await _load_message_page(db, room.id, before=None, limit=message_limit)

    setup = await _resolve_starting_setup(db, room)
    content_snapshot = None
    stats = None
    if setup is not None:
        content_snapshot = await _build_content_snapshot(db, room, setup)
        stat_rows = (
            await db.scalars(select(ChatRoomStat).where(ChatRoomStat.chat_room_id == room.id))
        ).all()
        stats = {str(row.stat_entity_id): float(row.current_value) for row in stat_rows}

    image_urls, cell_images = await _sign_message_images(db, room, setup, messages)
    # 다음 턴이 실제로 쓸 모델. 기본 모델 방이거나 상위 모델 스위치가 꺼져 있으면 쿼리가 없다.
    effective_model = await effective_room_model(db, room.user_id, room.chat_model)
    # 소설 유무는 허용 안 함 작품의 남의 방에서만 본다(방 하나에 소설 하나 — 방 유니크 인덱스로 찾는다).
    novel_creation_blocked = (
        content.novel_permission == "forbidden"
        and room.user_id != content.creator_user_id
        and await db.scalar(select(Novel.id).where(Novel.chat_room_id == room.id)) is None
    )

    # 미디어 북 태그는 첫 메시지(작성자 글을 칸 id 형태로 복사한 것)에서만 해석하고, 그중에서도 방 버전의
    # 시작설정 첫 메시지가 실제로 가리키는 칸만 서명한다. 오프닝은 지울 수 있어 첫 자리에 사용자 메시지나
    # 모델 응답이 올 수 있다 — 그 글의 칸 id 를 그대로 믿으면 플레이어가 아무 칸 id 나 쳐 넣거나 모델에게
    # 따라 쓰게 해서 아직 보지 못한 칸의 원본 URL 을 받는다.
    # 첫 메시지는 꼬리 창과 따로 읽는다 — 창에 오프닝이 없는 긴 방에서도, 위로 불러와 오프닝에 닿았을 때 그림이
    # 그려지도록 맵은 언제나 방의 실제 첫 메시지로 만든다.
    media_tag_images = {}
    if setup is not None:
        first_message = (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room.id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
                .limit(1)
            )
        ).first()
        first_refs = (
            media_tag_refs(first_message.content)
            if first_message is not None and first_message.role == ChatMessageRole.ASSISTANT
            else set()
        )
        if first_refs:
            _, opening_refs = await normalize_texts(
                db, room.content_version_id, [setup.opening_message or setup.prologue]
            )
            media_tag_images = await resolve_media_tag_images(
                db, room.content_version_id, first_refs & opening_refs
            )

    return ChatRoomResponse(
        id=room.id,
        content_id=room.content_id,
        content_type=content.type,
        name=_display_name(room, ordinal),
        starting_setup_id=setup.entity_id if setup is not None else None,
        turn_count=room.turn_count,
        ending_reached=room.ending_reached,
        stats=stats,
        messages=[
            _room_message_response(m, image_urls, cell_images)
            for m in messages
        ],
        has_more_messages_before=has_more_before,
        content_snapshot=content_snapshot,
        media_tag_images=media_tag_images,
        latest_version_available=content.current_published_version_id != room.content_version_id,
        version_auto_upgraded=room.version_auto_upgraded,
        persona_id=room.persona_id,
        persona_name=persona.name if persona is not None else None,
        default_user_name=version_detail.default_user_name,
        content_name=version_detail.name,
        content_restricted=content.moderation_status != ModerationStatus.NORMAL,
        novel_creation_blocked=novel_creation_blocked,
        chat_model=room.chat_model,
        effective_chat_model=effective_model,
        turn_cost=chat_turn_cost(effective_model),
        created_at=room.created_at,
        updated_at=room.updated_at,
    )


def _room_message_response(
    message: ChatMessage, image_urls: dict[uuid.UUID, str], cell_images: dict[uuid.UUID, MediaTagImage]
) -> ChatMessageResponse:
    cell_image = cell_images.get(message.image_id) if message.image_id is not None else None
    if cell_image is not None:
        return ChatMessageResponse(
            id=message.id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            image_id=message.image_id,
            image_url=cell_image.url,
            image_width=cell_image.width,
            image_height=cell_image.height,
        )
    return ChatMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        image_id=message.image_id,
        image_url=image_urls.get(message.image_id) if message.image_id is not None else None,
    )


async def _create_room(
    db: AsyncSession,
    user_id: uuid.UUID,
    content: Content,
    setup: StartingSetup | None,
    *,
    persona_id: uuid.UUID | None,
) -> ChatRoom:
    """`POST /chat-rooms`와 `POST /chat-rooms/{id}/change-starting-setup`이 공유하는
    방 생성 핵심 로직 — 항상 콘텐츠의 현재 발행 버전에 고정한다.

    `persona_id`는 받은 값만 쓴다. "새 방 = 기본"과 "원래
    방 승계" 규칙은 두 호출부가 각자 한 번씩 정한다. 둘 다 유저 행을 잠근 뒤에 값을
    읽어야 프로필 삭제와 엇갈려 FK 위반 500이 나지 않는다. 키워드 전용 필수라 새
    호출부가 값을 빠뜨리면 mypy가 잡는다."""
    room = ChatRoom(
        user_id=user_id,
        content_id=content.id,
        content_version_id=content.current_published_version_id,
        starting_setup_entity_id=setup.entity_id if setup is not None else None,
        persona_id=persona_id,
    )
    db.add(room)
    await db.flush()
    await record_chat_participant(db, content, user_id)

    if setup is not None:
        await _seed_initial_stats(db, room, setup)

    await _insert_opening_message(db, room, setup)
    return room


async def _resolve_setup_for_content(
    db: AsyncSession, content: Content, starting_setup_id: uuid.UUID
) -> StartingSetup:
    setup = await db.scalar(
        select(StartingSetup).where(
            StartingSetup.id == starting_setup_id,
            StartingSetup.content_version_id == content.current_published_version_id,
        )
    )
    if setup is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid startingSetupId")
    return setup


@router.post(  # 재동의 게이트
    "", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_legal_consent)]
)
async def create_chat_room(
    payload: ChatRoomCreateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomResponse:
    content = await db.get(Content, payload.content_id)
    if content is None or content.current_published_version_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")
    _ensure_content_playable(content)
    # 이용제한·삭제는 바로 위가 걸렀으므로 여기서 닫히는 것은 작가 아닌 사람의 비공개 작품(작가 탈퇴 포함)뿐이다.
    # 이미 방이 있는 사람도 새 방은 못 연다 — 비공개 작품에서는 기존 방에서 대화를 잇는 것만 된다.
    if not is_open_to(content, user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "CONTENT_PRIVATE"})

    expected_type = ContentType.STORY if payload.content_type == "story" else ContentType.CHARACTER
    if content.type != expected_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content type mismatch")

    setup: StartingSetup | None = None
    if payload.content_type == "story":
        if payload.starting_setup_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="startingSetupId is required for story chat rooms"
            )
        setup = await _resolve_setup_for_content(db, content, payload.starting_setup_id)

    # 새 방은 기본 프로필로 시작한다. 유저 행을 잠그면서 컬럼으로
    # 읽는다(`db.get(User)`는 락을 걸지 않는다 — `persona/router.py` 모듈 docstring).
    default_persona_id = await lock_user_default_persona(db, user_id)
    room = await _create_room(db, user_id, content, setup, persona_id=default_persona_id)
    await db.commit()

    return await _to_response(db, room)


@router.get("/{room_id}")
async def get_chat_room(
    room_id: uuid.UUID,
    message_limit: int | None = Query(None, alias="messageLimit", ge=1),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomResponse:
    room = await _get_owned_room(db, room_id, user_id)
    return await _to_response(db, room, message_limit=message_limit)


@router.get("/{room_id}/messages")
async def list_chat_messages_before(
    room_id: uuid.UUID,
    before: uuid.UUID,
    limit: int = Query(ge=1),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatMessagePageResponse:
    """위로 불러오기 — 커서 메시지 바로 앞의 메시지 최대 `limit` 개를 오래된 것부터. 커서는 이 방의 메시지여야
    한다(다른 방 메시지의 시각으로 이 방을 자르지 않는다)."""
    room = await _get_owned_room(db, room_id, user_id)
    cursor = await db.get(ChatMessage, before)
    if cursor is None or cursor.chat_room_id != room.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    messages, has_more_before = await _load_message_page(db, room.id, before=cursor, limit=limit)
    setup = await _resolve_starting_setup(db, room)
    image_urls, cell_images = await _sign_message_images(db, room, setup, messages)
    return ChatMessagePageResponse(
        messages=[_room_message_response(m, image_urls, cell_images) for m in messages],
        has_more_before=has_more_before,
    )


@router.get("/{room_id}/play-guide")
async def get_play_guide(
    room_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> PlayGuideResponse:
    """방이 고정한 버전 기준으로 플레이가이드를 온디맨드 조회한다 —
    contentSnapshot에는 의도적으로 포함하지 않는다."""
    room = await _get_owned_room(db, room_id, user_id)
    setup = await _require_starting_setup(db, room)
    if setup is not None:
        return PlayGuideResponse(play_guide=setup.playguide)

    detail = await db.get(CharacterVersionDetail, room.content_version_id)
    assert detail is not None
    return PlayGuideResponse(play_guide=detail.playguide)


_POLICY_WARNING_MESSAGE = "메시지 생성이 콘텐츠 정책에 의해 중단되었습니다."
# 문구의 유일한 자리. 3곳은 `_policy_warning_message`로만 고른다.
_PERSONA_POLICY_WARNING_MESSAGE = f"{_POLICY_WARNING_MESSAGE} 대화 프로필 내용이 원인일 수 있어요."
_NOTE_POLICY_WARNING_MESSAGE = f"{_POLICY_WARNING_MESSAGE} 기억 노트 내용이 원인일 수 있어요."
_PERSONA_AND_NOTE_POLICY_WARNING_MESSAGE = f"{_POLICY_WARNING_MESSAGE} 대화 프로필이나 기억 노트 내용이 원인일 수 있어요."
_GENERATION_ERROR_MESSAGE = "메시지 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."


def _policy_warning_message(persona_rendered: bool, note_rendered: bool) -> str:
    """그 턴 생성 프롬프트에 대화 프로필·기억 노트 섹션이 실제로
    들어갔을 때만(`user_persona_rendered`·`memory_note_rendered`) 그 안내를 붙이고, 둘 다면 한 문장으로
    합친다. 원인이 그것인지는 알 수 없어서 "~일 수 있다"로 쓴다. 요약은 대화에서 나온 것이라 안내에
    넣지 않는다. `yield ChatPolicyWarningEvent` 3곳이 공유한다(미리보기는 노트가 없어 거짓)."""
    if persona_rendered and note_rendered:
        return _PERSONA_AND_NOTE_POLICY_WARNING_MESSAGE
    if persona_rendered:
        return _PERSONA_POLICY_WARNING_MESSAGE
    if note_rendered:
        return _NOTE_POLICY_WARNING_MESSAGE
    return _POLICY_WARNING_MESSAGE


def _llm_dependency_tag(exc: LLMClientError | PromptRenderError | PromptSetNotFoundError) -> str:
    """이 파일의 생성/판정 흡수 지점 8곳이 공유하는 승격 태그
    분류다. `PromptRenderError`는 외부 의존이 아니라 우리 템플릿 결함이라 별도 태그로 갈라
    묶어 본다. 생성 세트가 없는 것(`PromptSetNotFoundError`)도 같은 묶음이다 — 둘 다 어드민 문안 쪽을 고쳐야 한다. LLM 실패는 공급자와 쿼터 소진(429) 여부로 가른다(`llm/client.py` 의 `dependency_tag`) —
    안 갈라 붙이면 승격된 이벤트가 행동 가능하지 않다."""
    if isinstance(exc, (PromptRenderError, PromptSetNotFoundError)):
        return "prompt_render"
    return dependency_tag(exc)


async def _lock_room_for_turn_write(db: AsyncSession, room: ChatRoom) -> uuid.UUID | None:
    """턴 쓰기 구간의 첫 문장 — 방 행을 잠그고 아직 있는지 본다. 없으면(LLM 을 기다리는 사이 사용자가 방을 지웠다)
    경고를 남기고 트랜잭션을 반납한 뒤 `None` 이다. 호출부는 아무것도 쓰지 않고 오류 이벤트로 끝낸다 — 환불하지
    않는다(사용자가 지웠고 LLM 은 이미 탔다).

    `FOR NO KEY UPDATE` 라 응답 INSERT 의 외래 키 확인(KEY SHARE)과는 부딪히지 않고, 방 행을 고치는 다른 쓰기(요약 접기의
    버전 갱신, 방 삭제의 첫 UPDATE)와는 줄을 선다 — 쓰기 구간은 짧다."""
    room_id = await db.scalar(select(ChatRoom.id).where(ChatRoom.id == room.id).with_for_update(key_share=True))
    if room_id is None:
        logger.warning("대화방 %s 이 응답을 만드는 사이 지워졌다 — 이번 턴은 저장하지 않는다", room.id)
        await db.commit()
    return room_id


def _dump_prompt(
    *, room_id: uuid.UUID | None, model: ChatModelId, turn: int, prompt: str, system_instruction: str
) -> None:
    """회차 재현용으로 조립된 프롬프트를 JSONL 한
    줄로 남긴다. 호출부는 `settings.prompt_dump_path is not None`일 때만 부른다.

    바닥 지시문도 함께 남긴다 — 실험에서 바꿔 가며 비교하는 것이 바로 그것이라, 대화록만 남고 그때
    어떤 지시문이 실렸는지 모르면 회차를 나중에 설명할 수 없다. 모델은 고른 모델(`chatModel`)과 실제로 보낸 모델 id
    (`model`)를 함께 남기고, 시드는 Gemini 만 받는 설정이라 Gemini 턴에만 적는다."""
    record = {
        "roomId": str(room_id) if room_id is not None else None,
        "turn": turn,
        "chatModel": model,
        "model": actual_model_id(model),
        "seed": settings.gemini_seed if model == "gemini" else None,
        "systemInstruction": system_instruction,
        "prompt": prompt,
    }
    assert settings.prompt_dump_path is not None
    with open(settings.prompt_dump_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


async def _stream_generated_tokens(
    llm_client: LLMClient,
    prompt: str,
    chunks: list[str],
    system_instruction: str,
    user_label: str,
    *,
    usage: LLMCallContext,
    turn: int,
) -> AsyncIterator[ChatTokenEvent]:
    """`llm_client.generate()`의 각 델타를 그대로 relay하며 호출부가 넘긴 빈 리스트 `chunks`에
    누적한다 — 제너레이터는 반환값과 yield를 동시에 쓸 수 없어, 스트림 종료 후 조립할 전체
    텍스트를 이 out-param으로 호출부에 넘긴다.

    바닥 지시문은 호출부가 골라 넘긴다(`system_instruction_for`) — 여기서 고를 수 없다.
    스토리/캐릭터 구분이 실제 방·미리보기에서 서로 다른 값(`setup`/`payload` 타입)으로
    드러나기 때문이다. `stop_sequences`는 `user_label`에서 파생한다 — 이 함수가 실채팅·미리보기 공용이라 한 번만 고치면 둘 다 덮인다.

    진입부에서 `settings.prompt_dump_path`가 설정돼 있으면(기본값 None, 프로덕션 방어) 조립된
    프롬프트와 그때 실린 지시문을 그 파일에 덤프한다. **덤프 실패는 절대 스트림을
    막지 않는다** — SSE 제너레이터 본문에서 새 예외가 새면 요청 스코프 DB 세션이 강제 종료돼
    무관한 다른 요청까지 500이 된다(apps/api/CLAUDE.md §SSE 스트리밍)."""
    if settings.prompt_dump_path is not None:
        try:
            _dump_prompt(
                room_id=usage.room_id,
                model=usage.model,
                turn=turn,
                prompt=prompt,
                system_instruction=system_instruction,
            )
        except Exception:
            logger.warning("프롬프트 덤프 실패 (room=%s, turn=%s)", usage.room_id, turn, exc_info=True)
    async for delta in llm_client.generate(
        prompt, system_instruction, stop_sequences=[f"\n{user_label}:"], usage=usage
    ):
        chunks.append(delta)
        yield ChatTokenEvent(delta=delta)


async def _stream_new_turn(
    db: AsyncSession,
    room: ChatRoom,
    llm_client: LLMClient,
    setup: StartingSetup | None,
    history: list[ChatMessage],
    user_content: str,
    shortcut: Shortcut | None,
    prompt_set: PromptSet,
    prompt_sections: list[PromptSection],
    charge: ChatCharge,
    session_factory: async_sessionmaker[AsyncSession],
    background_tasks: BackgroundTasks,
    settlement: TurnSettlement,
) -> AsyncIterator[ChatStreamEvent]:
    """생성 + 판단(buildJudgmentPrompt+generateStructured) + turn_count 증가까지 "새 턴
    하나"를 전부 실행한다. `send_message`(새 사용자 메시지)와 `edit_message`(수정된 메시지부터
    이어서 생성)가 공유한다 — 둘 다 실제로는 동일한 "새 턴"이고 차이는 호출부가 넘기는
    history/user_content뿐이다. 캐릭터 챗은 상황별 이미지 매칭만, 스토리 챗은 스탯 변경·엔딩 판정과
    미디어 북 칸 판정을 한다(그림 결과는 둘 다 `chat_messages.image_id`에 저장돼 done 이벤트의 finalMessage와
    `GET /chat-rooms/{id}` 재조회 둘 다에 실린다 — 캐릭터는 상황별 이미지 entity_id, 스토리는 칸 entity_id).
    스토리 챗은 최초 엔딩 도달(room.ending_reached) 이후로 스탯·엔딩 판정이 멈추고 칸 판정만 계속한다 —
    메시지 생성 자체는 계속 허용.

    `regenerate_message`(같은 턴의 응답만 교체, 스탯/엔딩 판단·turn_count 재실행 없음 —
    이미지 매칭은 재실행한다)는 이 헬퍼를 쓰지 않는다
    — 그 라우트의 docstring 참고.

    LLM(생성·판정)을 기다리는 동안 요청 세션은 트랜잭션을 쥐지 않는다 — 쥐면 그동안 커넥션 하나를 통째로 점유해,
    동시에 진행할 수 있는 턴 수가 커넥션 풀 크기에 묶인다. 그래서 턴은 세 구간으로 나뉜다: ① 읽기(생성 프롬프트,
    판정 입력) → 커밋으로 반납 → ② LLM(생성 스트림, 판정) → ③ 쓰기(응답 메시지·turn_count·노출·스탯·엔딩을 한
    트랜잭션으로). 반납은 `commit()` 이다 — 읽기만 한 트랜잭션이라 끝내기만 하고, `expire_on_commit=False` 라 읽어 둔
    객체를 그대로 쓴다(`rollback()` 은 객체를 만료시켜 다음 속성 접근이 실패한다). 쓰기를 마지막 한 구간에 모으는
    이유는 "응답 메시지와 판정 결과가 한 커밋"이라는 원자성을 지키려는 것이다 — 그래서 응답 메시지의 `created_at` 은
    판정이 끝난 시각이다. 같은 방의 다른 턴은 방 락(`_room_turn_lock_dependency`)이 막는다. 방 삭제는 락 대상이 아니라
    LLM 을 기다리는 사이 방이 사라질 수 있다 — 그때는 아무것도 쓰지 않고 오류 이벤트로 끝내며 환불하지 않는다(사용자가
    지웠고 LLM 은 이미 탔다).

    턴을 커밋한 뒤에는 긴 방의 요약 접기(`fold_memory`)를 background로 예약한다. 접을 때인지는
    접기 쪽이 새 세션으로 다시 읽어 판정한다(턴마다 예약하고 대부분은 읽기만 하고 끝난다).
    예약은 첫 사후 `yield` **앞**이다 — 그 뒤에 두면 `done`을 받고 연결을 끊은 클라이언트의
    턴에서 예약 자체가 사라진다. 커밋 뒤 조회(상황이미지 URL·칸 서명·에필로그)가 연 트랜잭션은 예약 전에 다시
    반납하고, 예약 뒤에는 요청 세션 쿼리를 더하지 않는다 — background는 요청 세션이 닫히기 전에 돌아서, 열린
    트랜잭션은 요약 호출 내내 커넥션을 쥔다.
    생성 윈도우 설정이 꺼져 있으면 요약을 싣지 않으므로 접기도 예약하지 않는다.
    """
    try:
        # 생성은 값을 낸 모델의 세트로, 판정·요약은 받은 Gemini 세트(`prompt_set`)로 한다.
        generation_set, generation_sections = await generation_prompt_set(
            db, lane=_lane_for_setup(setup), model=charge.model, gemini_set=(prompt_set, prompt_sections)
        )
        prompt, system_instruction, persona_rendered, note_rendered, names = await build_room_prompt(
            db, room, setup, history, user_content, shortcut, generation_set, generation_sections
        )
    except (PromptRenderError, PromptSetNotFoundError) as exc:
        # apps/api/CLAUDE.md §SSE: 이 예외를 여기서 흡수하지 않으면 제너레이터 본문을 뚫고
        # 나가 태스크 취소 → 커넥션 강제종료로 번진다. LLM 호출 전이므로 흡수해도 잃는
        # 게 없다 — 아직 아무 것도 스트리밍되지 않았다. 생성 세트가 없는 것도 같은 자리다(차감 뒤에야 모델을 안다).
        logger.warning("대화방 %s 프롬프트 렌더 실패: %s", room.id, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        # 환불은 `yield` **앞**이다 — 뒤에 두면 클라이언트가 이미 끊었을 때 실행되지 않는다.
        await settlement.refund()
        yield ChatErrorEvent(message=_GENERATION_ERROR_MESSAGE)
        return
    # 생성 프롬프트에 필요한 읽기는 끝났다 — 생성 스트림을 기다리는 동안 커넥션을 쥐지 않게 반납한다.
    await db.commit()

    next_turn = room.turn_count + 1
    chunks: list[str] = []
    try:
        async for token_event in _stream_generated_tokens(
            llm_client,
            prompt,
            chunks,
            system_instruction,
            generation_set.user_label,
            usage=LLMCallContext(
                call_site="chat_generate", user_id=room.user_id, room_id=room.id, model=charge.model
            ),
            turn=next_turn,
        ):
            yield token_event
    except LLMPolicyViolationError:
        # 환불하지 않는다 — 사용자 입력이 원인이고 LLM 을 실제로
        # 태웠다. 이미지 가드 차단이 환불되는 것과 결론이 갈리는 자리다.
        settlement.mark_settled()
        yield ChatPolicyWarningEvent(message=_policy_warning_message(persona_rendered, note_rendered))
        return
    except LLMClientError as exc:
        logger.warning("대화방 %s 메시지 생성 실패: %s", room.id, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        await settlement.refund()
        yield ChatErrorEvent(message=_GENERATION_ERROR_MESSAGE)
        return

    assistant_content = "".join(chunks)

    stat_change_events: list[ChatStatChangeEvent] = []
    ending_reached_event: ChatEndingReachedEvent | None = None
    matched_image: SituationalImage | None = None
    judged_cell_id: uuid.UUID | None = None
    # 판정 결과는 쓰기 구간에서 한꺼번에 쓴다 — 스탯 행(키 → 행), 바뀐 스탯 값, 도달한 엔딩.
    stat_rows: dict[str, ChatRoomStat] = {}
    stat_writes: dict[str, float] = {}
    reached_ending: Ending | None = None
    # 판정 단계의 LLM 실패는 반드시 이 안에서 흡수한다 — 예외가 SSE 제너레이터 밖으로 새면
    # ASGI 태스크가 취소되면서 요청 스코프 DB 세션이 강제 종료되고, 망가진 asyncpg 커넥션이
    # 풀로 돌아가 그걸 집어간 **무관한 다른 요청**이 InterfaceError로 500이 난다(부하 실측).
    # 이미 응답은 스트리밍됐으니, 그 턴의 판정만 포기하고(그 전까지 나온 판정 결과는 그대로 쓴다)
    # 정상적으로 커밋 → done 이벤트까지 마무리하는 것이 실패의 폭발 반경을 그 턴에 가둔다.
    try:
        if setup is not None:
            # 스토리: 스탯 판정(최초 엔딩 전만)과 미디어 북 칸 판정(엔딩 뒤에도)을 동시에 부른다. DB 읽기는 전부
            # gather 앞(그리고 반납 커밋 앞), 쓰기는 전부 쓰기 구간이다 — gather 안의 두 코루틴은 LLM 만 부른다. 둘 다
            # 자기 LLM 실패를 흡수해 한쪽이 실패해도 다른 쪽 결과가 남는다.
            stat_request: StatJudgmentRequest | None = None
            stat_defs: list[StatDef] = []
            current_stats: dict[str, float] = {}
            due_endings: _DueEndings | None = None
            if not room.ending_reached:
                stat_defs, stat_rows, current_stats = await load_room_stats(db, room.id, setup.id)
                stat_request = prepare_stat_judgment(
                    prompt_set=prompt_set,
                    sections=prompt_sections,
                    stat_defs=stat_defs,
                    rules_by_stat_id=await _load_stat_rules(db, stat_defs),
                    user_message=user_content,
                    assistant_message=assistant_content,
                    names=names,
                )
                due_endings = await _load_due_endings(db, room, setup, history, next_turn)
            media_judgment = await _prepare_media_cell_judgment(
                db,
                room,
                prompt_set=prompt_set,
                prompt_sections=prompt_sections,
                history=history,
                user_message=user_content,
                assistant_message=assistant_content,
                names=names,
            )
            await db.commit()

            log_subject = f"대화방 {room.id}"
            updated_stats, judged_cell_id = await asyncio.gather(
                _await_stat_judgment(
                    llm_client,
                    stat_request,
                    LLMCallContext(call_site="chat_stat_judgment", user_id=room.user_id, room_id=room.id),
                    log_subject=log_subject,
                    current_stats=current_stats,
                    stat_defs=stat_defs,
                )
                if stat_request is not None
                else _no_judgment(),
                _judge_media_cell(
                    llm_client,
                    media_judgment,
                    LLMCallContext(call_site="chat_media_book_image", user_id=room.user_id, room_id=room.id),
                    log_subject=log_subject,
                )
                if media_judgment is not None
                else _no_judgment(),
            )

            if updated_stats is not None:
                for stat_id, new_value in updated_stats.items():
                    if new_value != current_stats.get(stat_id):
                        stat_writes[stat_id] = new_value
                        stat_change_events.append(ChatStatChangeEvent(stat_id=stat_id, new_value=new_value))

                # 엔딩 판정: 엔딩별 turn_count_gate를 넘긴 시점부터 5턴마다만 호출하고, 그 외 턴은 스킵한다.
                # 스탯 규칙을 통과한 엔딩만, `_endings_to_judge` 가 정한 순서(목록 순서, 우선 스탯을 채운 엔딩끼리는
                # 그 값이 가장 높은 것만, 그 뒤는 없음)로 판정해 첫 충족 엔딩에서 멈춘다(동시 충족 시 하나만 발동).
                # 스탯 반영 뒤라 순차다.
                assert due_endings is not None  # 스탯 판정은 엔딩 전에만 돌고, 그때 엔딩도 함께 읽었다.
                for ending in _endings_to_judge(
                    [
                        (ending, ending.entity_id, ending.priority_stat_def_entity_id, rule_items)
                        for ending, rule_items in due_endings.endings
                    ],
                    updated_stats,
                    log_subject=log_subject,
                ):
                    ending_judgment_prompt = build_ending_judgment_prompt(
                        prompt_set=prompt_set,
                        sections=prompt_sections,
                        judgment_prompt=ending.judgment_prompt,
                        history=due_endings.history,
                        user_message=user_content,
                        assistant_message=assistant_content,
                        memory_summary=due_endings.summary,
                        names=names,
                    )
                    ending_judgment = await llm_client.generate_structured(
                        ending_judgment_prompt,
                        EndingJudgmentResult,
                        usage=LLMCallContext(call_site="chat_ending_judgment", user_id=room.user_id, room_id=room.id),
                    )
                    if not ending_judgment.triggered:
                        continue
                    reached_ending = ending
                    ending_reached_event = ChatEndingReachedEvent(ending_id=ending.entity_id, epilogue=ending.epilogue)
                    break
        else:
            situational_judgment = await _prepare_situational_image_judgment(
                db,
                room,
                prompt_set=prompt_set,
                prompt_sections=prompt_sections,
                history=history,
                user_message=user_content,
                assistant_message=assistant_content,
                names=names,
            )
            await db.commit()
            if situational_judgment is not None:
                matched_image = await _judge_situational_image(llm_client, situational_judgment, room)
    except (LLMClientError, PromptRenderError) as exc:
        logger.warning("대화방 %s 판정 실패 — 이번 턴의 판정을 건너뛴다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))

    # 쓰기 구간. 방 행을 먼저 잠그며 존재를 확인한다 — 쓰기 구간끼리(요약 접기의 버전 갱신 포함) 줄을 서고, LLM 을
    # 기다리는 사이 방이 지워졌으면 응답 INSERT 가 외래 키 위반으로 제너레이터를 뚫기 전에 갈라진다.
    if await _lock_room_for_turn_write(db, room) is None:
        settlement.mark_settled()
        yield ChatErrorEvent(message=_GENERATION_ERROR_MESSAGE)
        return

    assistant_message = ChatMessage(
        chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content=assistant_content
    )
    db.add(assistant_message)
    await db.flush()
    # 여기부터 아래 커밋이 돌아올 때까지 끊기면 응답이 저장됐는지 알 수 없다 — 정산이 응답 행을 직접 확인한다.
    settlement.set_pending_message(db, room.id, assistant_message.id)
    room.turn_count = next_turn

    if judged_cell_id is not None and not await _record_story_media_exposure(db, room, judged_cell_id):
        judged_cell_id = None
    if matched_image is not None and not await _record_character_image_exposure(db, room, matched_image.entity_id):
        matched_image = None

    for stat_id, new_value in stat_writes.items():
        _write_room_stat(db, room.id, stat_rows, stat_id, new_value)

    if reached_ending is not None:
        assert setup is not None  # 엔딩은 스토리 방에만 있다.
        room.ending_reached = True
        room.ending_entity_id = reached_ending.entity_id
        room.ending_reached_at_turn = next_turn

        existing_unlock = await db.scalar(
            select(StoryEndingUnlock).where(
                StoryEndingUnlock.user_id == room.user_id,
                StoryEndingUnlock.starting_setup_entity_id == setup.entity_id,
                StoryEndingUnlock.ending_entity_id == reached_ending.entity_id,
            )
        )
        if existing_unlock is None:
            db.add(
                StoryEndingUnlock(
                    user_id=room.user_id,
                    starting_setup_entity_id=setup.entity_id,
                    ending_entity_id=reached_ending.entity_id,
                )
            )
        await _unlock_epilogue_cells(db, room, reached_ending.epilogue)

    if matched_image is not None:
        assistant_message.image_id = matched_image.entity_id
    elif judged_cell_id is not None:
        assistant_message.image_id = judged_cell_id

    await db.commit()
    # 응답이 저장됐다 — 이 뒤로 끊겨도 차감은 소모다.
    settlement.mark_settled()

    matched_image_url: str | None = None
    if matched_image is not None:
        # 매칭 필터가 image_asset_id가 NULL인
        # 후보를 판단 프롬프트에서 걸러내지만, 그 필터를 통과한 뒤에도 `db.get(Asset, ...)`
        # 실패와 S3 presign 실패는 남는다 — 이미 db.commit() 뒤라 예외가 여기서 새면
        # §SSE의 폭발 반경(커넥션 강제종료 → 무관한 다른 요청 500)이 그대로 열린다. 실패하면
        # 이 턴의 이미지 매칭만 포기하고 이미지 없이 done 이벤트로 마무리한다.
        try:
            assert matched_image.image_asset_id is not None
            image_asset = await db.get(Asset, matched_image.image_asset_id)
            assert image_asset is not None
            matched_image_url = await run_in_threadpool(generate_presigned_get_url, image_asset.storage_key)
        except Exception as exc:
            logger.warning("대화방 %s 상황이미지 URL 조립 실패 — 이미지 없이 진행한다: %s", room.id, exc)
            capture_dependency_failure(exc, dependency="s3")
            matched_image = None
            matched_image_url = None

    judged_cell_image = await _sign_judged_cell(db, room, judged_cell_id) if judged_cell_id is not None else None

    if ending_reached_event is not None and ending_reached_event.epilogue:
        # 에필로그의 미디어 북 태그를 방 버전의 칸 id 형태로 바꾸고 그림을 서명한다. 커밋 뒤라 여기서 예외가
        # 새면 SSE 제너레이터를 뚫으므로 흡수하고, 그때는 태그를 지운 글로 그림 없이 보낸다(이름 형태 태그를
        # 화면에 남기지 않는다). `fold_memory` 예약 앞이어야 한다 — 예약 뒤에는 요청 세션 쿼리를 더하지 않는다.
        epilogue = ending_reached_event.epilogue
        try:
            [epilogue_text], epilogue_images = await normalize_texts_for_display(
                db, room.content_version_id, [epilogue]
            )
        except Exception as exc:
            logger.warning("대화방 %s 에필로그 그림 해석 실패 — 태그 없이 보낸다: %s", room.id, exc)
            capture_dependency_failure(exc, dependency="db")
            epilogue_text, epilogue_images = strip_media_tags(epilogue), {}
        ending_reached_event = ending_reached_event.model_copy(
            update={"epilogue": epilogue_text, "media_tag_images": epilogue_images}
        )

    # 커밋 뒤 조회가 다시 연 트랜잭션을 반납한다 — 요청 세션은 아래 요약 접기(LLM 호출)가 끝난 뒤에야 닫힌다.
    await db.commit()

    if settings.memory_window_generation:
        background_tasks.add_task(
            fold_memory,
            session_factory,
            llm_client,
            room_id=room.id,
            user_id=room.user_id,
            prompt_set=prompt_set,
            sections=prompt_sections,
            is_story_chat=setup is not None,
            names=names,
        )

    for stat_change_event in stat_change_events:
        yield stat_change_event

    if ending_reached_event is not None:
        yield ending_reached_event

    yield ChatDoneEvent(
        final_message=_turn_message_response(
            assistant_message, matched_image, matched_image_url, judged_cell_id, judged_cell_image
        )
    )


@router.post("/{room_id}/messages", response_class=EventSourceResponse)
async def send_message(
    payload: ChatMessageCreateRequest,
    # 턴 뒤 요약 접기 예약용(`_stream_new_turn`).
    background_tasks: BackgroundTasks,
    # SSE 제너레이터라 시그니처에 Depends로 붙인다
    # (dependencies=처럼 본문 실행 전에 해석되지만, 이 파일의 `_owned_room_dependency`
    # 관례와 일관되게 시그니처 쪽을 골랐다) — 소유권 검사(room)보다 먼저 두어 존재하지
    # 않는 room_id에서도 404가 아니라 403이 먼저 뜨게 한다.
    _consent: None = Depends(require_legal_consent),
    room: ChatRoom = Depends(_playable_room_dependency),
    # 방 락(진행 중 턴이면 409). 단축어 검증과 차감 게이트보다 앞이다(`_room_turn_lock_dependency`).
    turn_lock: RoomTurnLock = Depends(_room_turn_lock_dependency),
    shortcut: Shortcut | None = Depends(_validate_shortcut),
    db: AsyncSession = Depends(get_db_session),
    # 환불은 별도 트랜잭션이라 요청 세션(`db`)으로는 못 한다
    # — 차감이 이미 커밋된 뒤라 같은 세션에 얹으면 라우트가 롤백될 때 환불만 사라진다.
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
    prompt_set_data: tuple[PromptSet, list[PromptSection]] = Depends(_active_prompt_set_dependency),
    setup: StartingSetup | None = Depends(_starting_setup_dependency),
    # 차감 게이트: 반환형이 `None`에서
    # `ChatCharge`로 바뀌었다(무엇으로 냈는지가 환불 대상을 가른다).
    # 🔴 mypy는 이 어노테이션을 **검증하지 않는다** — `Depends(...)`가 `Any`라 `None`으로
    # 둬도 통과한다. 게이트 반환형을 바꿀 때 이 4곳은 손으로 찾아야 한다.
    #
    # 🔴 **조회·검증 의존성 전부보다 뒤에 둔다**. `Depends`는
    # 시그니처 순서대로 순차 resolve되고 앞의 것이 raise하면 뒤는 호출조차 안 되므로
    # (`apps/api/CLAUDE.md` §API 라우터), 게이트가 앞에 있으면 404(없는 방)·400(단축어·시작설정
    # 불일치)·`get_llm_client`의 ValueError에서 **차감만 남고 환불되지 않는다**. 그 창은 정상
    # 운영 중에도 열린다(지워진 방, 남의 방).
    # `_consent`(403)만 게이트보다 앞이다 — "재동의가 429보다 먼저"라는 기존 계약을 지킨다
    # (`images/router.py`의 같은 주석).
    # 대가: 실패하는 요청은 분당 버스트 상한에 세지지 않는다. 그게 상한의 목적(Gemini·GPU
    # 폭주 방어)에는 오히려 맞다 — 실패한 요청은 둘 다 안 태운다. "상한이 DB를 보호한다"는
    # 근거로는 쓸 수 없는데, 재동의 검사가 이미 게이트보다 앞에서 DB를 치고 있어 그 명제는
    # 이 변경 전에도 부분적으로만 참이었다.
    # 방의 세 경로는 방이 고른 모델로 가격을 정하는 게이트(`enforce_room_chat_charge`), 미리보기는 Gemini 게이트다.
    charge: ChatCharge = Depends(enforce_room_chat_charge),
) -> AsyncIterator[ChatStreamEvent]:
    """text/event-stream SSE 응답. 실제 생성+판단 파이프라인은
    `_stream_new_turn`(이 방의 새 사용자 메시지를 커밋한 뒤 호출)이 담당한다.

    본문 전체가 정산 가드 안이다 — 첫 `yield` 전 실패, 생성 중 끊김, 예상하지 못한 예외 어느 것으로 끝나도 응답이
    저장되지 않았으면 차감을 되돌리고 원래 예외를 다시 올린다(`chat/turn_settlement.py`)."""
    settlement = TurnSettlement(charge=charge, user_id=room.user_id, session_factory=session_factory)
    try:
        async with settlement.guard():
            prompt_set, prompt_sections = prompt_set_data

            history = list(
                (
                    await db.scalars(
                        select(ChatMessage)
                        .where(ChatMessage.chat_room_id == room.id)
                        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
                    )
                ).all()
            )

            # 사용자 메시지는 Gemini 호출 전에 먼저 커밋한다 — 이후 생성이 실패해도
            # 이미 저장된 사용자 메시지는 영향받지 않아야 하기 때문.
            user_message = ChatMessage(
                chat_room_id=room.id, role=ChatMessageRole.USER, content=payload.content
            )
            db.add(user_message)
            await db.commit()

            async for event in _stream_new_turn(
                db,
                room,
                llm_client,
                setup,
                history,
                payload.content,
                shortcut,
                prompt_set,
                prompt_sections,
                charge,
                session_factory,
                background_tasks,
                settlement,
            ):
                yield event
    finally:
        # 방 락 해제의 첫 자리(`_room_turn_lock_dependency`). 의존성 정리는 요약 접기 background 뒤에야 돌므로
        # 여기서 먼저 풀어야 접는 동안 다음 턴이 409 를 받지 않는다.
        await release_room_turn_lock(turn_lock)


async def _regeneratable_last_message_dependency(
    room: ChatRoom = Depends(_owned_room_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> ChatMessage:
    """소유권 검증(`_owned_room_dependency`)과 같은 이유로 별도 Depends로 분리한다 — SSE
    제너레이터 본문 안에서 HTTPException을 raise하면 안 된다. 재생성 대상은 방의 마지막
    메시지가 AI 응답이어야 하고, 그 앞에 사용자 메시지가 최소 하나는 있어야 한다(오프닝
    메시지만 있는 방은 재생성할 응답 자체가 없다)."""
    messages = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room.id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            )
        ).all()
    )
    if len(messages) < 2 or messages[-1].role != ChatMessageRole.ASSISTANT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No assistant response to regenerate"
        )
    return messages[-1]


@router.post("/{room_id}/regenerate", response_class=EventSourceResponse)
async def regenerate_message(
    # send_message와 같은 이유로 시그니처 Depends
    _consent: None = Depends(require_legal_consent),
    room: ChatRoom = Depends(_playable_room_dependency),
    # 방 락(진행 중 턴이면 409). 마지막 메시지 검증과 차감 게이트보다 앞이다(`_room_turn_lock_dependency`).
    turn_lock: RoomTurnLock = Depends(_room_turn_lock_dependency),
    last_message: ChatMessage = Depends(_regeneratable_last_message_dependency),
    db: AsyncSession = Depends(get_db_session),
    # 환불은 별도 트랜잭션이라 요청 세션(`db`)으로는 못 한다
    # — 차감이 이미 커밋된 뒤라 같은 세션에 얹으면 라우트가 롤백될 때 환불만 사라진다.
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
    prompt_set_data: tuple[PromptSet, list[PromptSection]] = Depends(_active_prompt_set_dependency),
    setup: StartingSetup | None = Depends(_starting_setup_dependency),
    # 차감 게이트(mypy가 안 잡는다, 조회·검증
    # 의존성 전부보다 뒤에 둔다 — `send_message`의 같은 자리 주석 참조)
    charge: ChatCharge = Depends(enforce_room_chat_charge),
) -> AsyncIterator[ChatStreamEvent]:
    """마지막 AI 응답만 새로 생성해 교체한다(기존 메시지 전송과 동일한 SSE 이벤트
    스키마). `send_message`/`edit_message`와 달리 새 턴이 아니라 같은 턴의 응답을 바꾸는
    것이므로 `_stream_new_turn`을 재사용하지 않는다 — turn_count는 증가시키지 않고, 스탯/엔딩
    판단은 재실행하지 않는다(원 응답 생성 시 이미 한 번 반영됐고, 그 반영분을 되돌릴 턴별
    이력이 없어 재실행하면 오히려 중복 적용되어 부정확해진다). 그림 판정(캐릭터 상황별 이미지·스토리 미디어
    북 칸 — 스토리는 엔딩 뒤에도)은 재실행한다 — 노출 기록(`CharacterImageExposure`·`StoryMediaExposure`)은
    첫 노출만 기록해 멱등이라 재실행이 중복 적용을 만들지 않고, 새 응답 텍스트에 맞는 그림이 붙는다. 생성이 실패하면(policyWarning/error) 기존
    응답을 그대로 둔다 — 대체 텍스트가 확정되기 전까지는 메시지를 건드리지 않는다. 바꿀 응답을
    덮던 요약은 생성 전에 되감겨 커밋되므로 생성이 실패해도 되돌아오지 않는다.

    트랜잭션 구간은 `_stream_new_turn` 과 같다 — 생성·판정 LLM 앞에서 요청 세션을 커밋으로 반납하고, 옛 응답 삭제와
    새 응답·노출 기록은 판정 뒤 한 트랜잭션으로 쓴다(방이 그사이 지워졌으면 쓰지 않고 오류 이벤트로 끝낸다)."""
    # 정산 가드는 `send_message` 와 같다.
    settlement = TurnSettlement(charge=charge, user_id=room.user_id, session_factory=session_factory)
    try:
        async with settlement.guard():
            prompt_set, prompt_sections = prompt_set_data

            # `history[-1]`은 의존성이 "마지막 앞에 사용자 메시지가 있어야 한다"로 막고 있어 현재는
            # 도달 불가지만, 그 가드가 느슨해지면 여기서 IndexError 가 난다.
            # 바꿀 응답이 요약 커서 메시지 자신이면(커서 뒤를 전부 지운 방) 그 요약을 되감는다 — 안 그러면
            # 옛 응답이 요약에 남고 윈도우는 오프닝만 남긴다. 되감기는 생성보다 먼저 커밋한다: 방 행 락을
            # 생성 내내 쥐지 않고, 윈도우가 되감긴 커서로 계산된다. 생성이 실패해도 되돌리지 않는다.
            await rewind_memory(db, room.id, (last_message.created_at, last_message.id))
            await db.commit()
            history = list(
                (
                    await db.scalars(
                        select(ChatMessage)
                        .where(ChatMessage.chat_room_id == room.id, ChatMessage.id != last_message.id)
                        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
                    )
                ).all()
            )
            user_content = history[-1].content
            try:
                # 생성 세트는 `_stream_new_turn` 의 같은 자리와 같다(판정은 Gemini 세트).
                generation_set, generation_sections = await generation_prompt_set(
                    db, lane=_lane_for_setup(setup), model=charge.model, gemini_set=(prompt_set, prompt_sections)
                )
                prompt, system_instruction, persona_rendered, note_rendered, names = await build_room_prompt(
                    db, room, setup, history[:-1], user_content, None, generation_set, generation_sections
                )
            except (PromptRenderError, PromptSetNotFoundError) as exc:
                logger.warning("대화방 %s 재생성 프롬프트 렌더 실패: %s", room.id, exc)
                capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
                # 환불은 `yield` 앞이다(`_stream_new_turn`의 같은 자리 주석 참조).
                await settlement.refund()
                yield ChatErrorEvent(message=_GENERATION_ERROR_MESSAGE)
                return
            # 생성 스트림을 기다리는 동안 커넥션을 쥐지 않게 반납한다(`_stream_new_turn` 의 같은 자리).
            await db.commit()

            chunks: list[str] = []
            try:
                async for token_event in _stream_generated_tokens(
                    llm_client,
                    prompt,
                    chunks,
                    system_instruction,
                    generation_set.user_label,
                    usage=LLMCallContext(
                        call_site="chat_generate", user_id=room.user_id, room_id=room.id, model=charge.model
                    ),
                    # 재생성은 turn_count 를 올리지 않는다 — 같은 턴의 응답을 교체하는 것이다.
                    turn=room.turn_count,
                ):
                    yield token_event
            except LLMPolicyViolationError:
                # 환불하지 않는다.
                settlement.mark_settled()
                yield ChatPolicyWarningEvent(message=_policy_warning_message(persona_rendered, note_rendered))
                return
            except LLMClientError as exc:
                logger.warning("대화방 %s 응답 재생성 실패: %s", room.id, exc)
                capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
                await settlement.refund()
                yield ChatErrorEvent(message=_GENERATION_ERROR_MESSAGE)
                return

            assistant_content = "".join(chunks)

            matched_image: SituationalImage | None = None
            judged_cell_id: uuid.UUID | None = None
            # send_message와 같은 이유(§SSE)로 판정 실패를 흡수한다 — 이미 생성된 응답까지 버리지
            # 않고 그 턴의 이미지 매칭만 포기한다. 판정 입력 읽기 뒤, LLM 앞에서 요청 세션을 반납한다.
            if setup is None:
                try:
                    situational_judgment = await _prepare_situational_image_judgment(
                        db,
                        room,
                        prompt_set=prompt_set,
                        prompt_sections=prompt_sections,
                        history=history[:-1],
                        user_message=user_content,
                        assistant_message=assistant_content,
                        names=names,
                    )
                    await db.commit()
                    if situational_judgment is not None:
                        matched_image = await _judge_situational_image(llm_client, situational_judgment, room)
                except (LLMClientError, PromptRenderError) as exc:
                    logger.warning("대화방 %s 재생성 이미지 매칭 실패 — 이번 재생성의 매칭을 건너뛴다: %s", room.id, exc)
                    capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
            else:
                # 스토리: `_stream_new_turn` 의 칸 판정과 같은 헬퍼·같은 규칙(엔딩 여부와 무관, 노출 제외 칸은 후보 밖,
                # 실패는 그림만 포기). 스탯·엔딩 판정은 재생성에서 하지 않으므로 동시에 부를 짝이 없다.
                media_judgment = await _prepare_media_cell_judgment(
                    db,
                    room,
                    prompt_set=prompt_set,
                    prompt_sections=prompt_sections,
                    history=history[:-1],
                    user_message=user_content,
                    assistant_message=assistant_content,
                    names=names,
                )
                await db.commit()
                if media_judgment is not None:
                    judged_cell_id = await _judge_media_cell(
                        llm_client,
                        media_judgment,
                        LLMCallContext(call_site="chat_media_book_image", user_id=room.user_id, room_id=room.id),
                        log_subject=f"대화방 {room.id} 재생성",
                    )

            # 쓰기 구간(`_stream_new_turn` 의 같은 자리 주석 참조).
            if await _lock_room_for_turn_write(db, room) is None:
                settlement.mark_settled()
                yield ChatErrorEvent(message=_GENERATION_ERROR_MESSAGE)
                return
            await db.execute(delete(ChatMessage).where(ChatMessage.id == last_message.id))
            # 옛 응답 DELETE 와 같은 트랜잭션이라 응답이 실제로 지워진 재생성만 센다 — 렌더 실패·정책
            # 위반·LLM 오류는 위에서 옛 응답을 남긴 채 끝나므로 기록되지 않는다.
            db.add(DiscardedResponse(user_id=room.user_id, chat_room_id=room.id, kind="regenerate", discarded_count=1))
            # id 를 여기서 정한다 — 컬럼 기본값(`uuid4`)은 flush 때에야 채워지는데, 정산은 커밋 전에 이 id 를 알아야 한다.
            new_message = ChatMessage(
                id=uuid.uuid4(), chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content=assistant_content
            )
            db.add(new_message)
            # 여기부터 아래 커밋이 돌아올 때까지 끊기면 응답이 저장됐는지 알 수 없다(`_stream_new_turn` 의 같은 자리).
            settlement.set_pending_message(db, room.id, new_message.id)

            if matched_image is not None and not await _record_character_image_exposure(
                db, room, matched_image.entity_id
            ):
                matched_image = None
            if judged_cell_id is not None and not await _record_story_media_exposure(db, room, judged_cell_id):
                judged_cell_id = None

            if matched_image is not None:
                new_message.image_id = matched_image.entity_id
            elif judged_cell_id is not None:
                new_message.image_id = judged_cell_id

            await db.commit()
            settlement.mark_settled()

            matched_image_url: str | None = None
            if matched_image is not None:
                # send_message(_stream_new_turn)와 같은 이유로
                # 미러링한다 — 매칭 필터가 image_asset_id가 NULL인 후보를 판단 프롬프트에서
                # 걸러내지만, 그 필터를 통과한 뒤에도 `db.get(Asset, ...)` 실패와 S3 presign 실패는
                # 남는다 — 이미 db.commit() 뒤라 예외가 여기서 새면 §SSE의 폭발 반경(커넥션
                # 강제종료 → 무관한 다른 요청 500)이 그대로 열린다. 실패하면 이번 재생성의 이미지
                # 매칭만 포기하고 이미지 없이 done 이벤트로 마무리한다.
                try:
                    assert matched_image.image_asset_id is not None
                    image_asset = await db.get(Asset, matched_image.image_asset_id)
                    assert image_asset is not None
                    matched_image_url = await run_in_threadpool(generate_presigned_get_url, image_asset.storage_key)
                except Exception as exc:
                    logger.warning("대화방 %s 재생성 상황이미지 URL 조립 실패 — 이미지 없이 진행한다: %s", room.id, exc)
                    capture_dependency_failure(exc, dependency="s3")
                    matched_image = None
                    matched_image_url = None

            judged_cell_image = (
                await _sign_judged_cell(db, room, judged_cell_id) if judged_cell_id is not None else None
            )
            # 커밋 뒤 조회가 다시 연 트랜잭션을 반납한다.
            await db.commit()

            yield ChatDoneEvent(
                final_message=_turn_message_response(
                    new_message, matched_image, matched_image_url, judged_cell_id, judged_cell_image
                )
            )
    finally:
        # 방 락 해제의 첫 자리(`_room_turn_lock_dependency`). 의존성 정리보다 먼저 풀어야 다음 요청이 기다리지 않는다.
        await release_room_turn_lock(turn_lock)


async def _editable_user_message_dependency(
    message_id: uuid.UUID,
    room: ChatRoom = Depends(_owned_room_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> ChatMessage:
    """소유권 검증과 같은 이유로 별도 Depends로 분리(SSE 제너레이터 본문에서 HTTPException 금지).
    수정 대상은 반드시 이 방에 속한 사용자 메시지여야 한다 — AI 메시지 수정은 지원하지 않는다
    (요구사항은 "사용자 메시지 수정"뿐이다)."""
    message = await db.get(ChatMessage, message_id)
    if message is None or message.chat_room_id != room.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    if message.role != ChatMessageRole.USER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only user messages can be edited")
    return message


@router.patch("/{room_id}/messages/{message_id}", response_class=EventSourceResponse)
async def edit_message(
    payload: ChatMessageEditRequest,
    # 턴 뒤 요약 접기 예약용(`_stream_new_turn`).
    background_tasks: BackgroundTasks,
    # send_message와 같은 이유로 시그니처 Depends
    _consent: None = Depends(require_legal_consent),
    room: ChatRoom = Depends(_playable_room_dependency),
    # 방 락(진행 중 턴이면 409). 대상 메시지 검증과 차감 게이트보다 앞이다(`_room_turn_lock_dependency`).
    turn_lock: RoomTurnLock = Depends(_room_turn_lock_dependency),
    message: ChatMessage = Depends(_editable_user_message_dependency),
    db: AsyncSession = Depends(get_db_session),
    # 환불은 별도 트랜잭션이라 요청 세션(`db`)으로는 못 한다
    # — 차감이 이미 커밋된 뒤라 같은 세션에 얹으면 라우트가 롤백될 때 환불만 사라진다.
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
    prompt_set_data: tuple[PromptSet, list[PromptSection]] = Depends(_active_prompt_set_dependency),
    setup: StartingSetup | None = Depends(_starting_setup_dependency),
    # 차감 게이트(mypy가 안 잡는다, 조회·검증
    # 의존성 전부보다 뒤에 둔다 — `send_message`의 같은 자리 주석 참조)
    charge: ChatCharge = Depends(enforce_room_chat_charge),
) -> AsyncIterator[ChatStreamEvent]:
    """수정된 메시지 이후의 모든 메시지를 삭제하고 수정된 내용부터 새 AI 응답을 이어서
    생성한다. `send_message`와 마찬가지로 완전히 새로운 턴이라 `_stream_new_turn`
    (판단 단계 + turn_count 증가 포함)을 그대로 재사용한다 — 차이는 새 사용자 메시지를
    추가하는 대신 기존 메시지를 갱신하고, history가 그 메시지 이전까지로 잘린다는 점뿐이다.

    삭제되는 메시지 중 AI 응답 개수만큼 turn_count를 미리 되돌려둔다(그래야 `_stream_new_turn`의
    +=1과 합쳐 실제 남은 대화 길이와 일치하고, 이후 엔딩 턴게이트 판정이 어긋나지 않는다).
    다만 삭제된 턴들이 이미 반영해 둔 chat_room_stats/ending_reached 등의 상태까지 되돌리는
    건 하지 않는다 — 되돌릴 근거가 되는 턴별 변경 이력 자체가 저장되어 있지 않고
    (알려진 한계), 요구사항에도 이 롤백은 없다.
    """
    # 정산 가드는 `send_message` 와 같다. 첫 `yield` 전 구간은 조회·DELETE·커밋이 다 들어 있어 세 라우트 중 위험이 가장 크다.
    settlement = TurnSettlement(charge=charge, user_id=room.user_id, session_factory=session_factory)
    try:
        async with settlement.guard():
            prompt_set, prompt_sections = prompt_set_data

            # 요약 되감기가 먼저다 — 편집 지점이 요약된 구간이면 커서가 그 앞으로 물러나야, 아래에서 자른
            # 히스토리가 생성 프롬프트에서 복귀한 커서 기준으로 실린다. 절단·편집과 한 트랜잭션이다.
            await rewind_memory(db, room.id, (message.created_at, message.id))
            all_messages = list(
                (
                    await db.scalars(
                        select(ChatMessage)
                        .where(ChatMessage.chat_room_id == room.id)
                        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
                    )
                ).all()
            )
            edited_index = next(i for i, m in enumerate(all_messages) if m.id == message.id)
            history = all_messages[:edited_index]
            trailing = all_messages[edited_index + 1 :]

            if trailing:
                removed_turns = sum(1 for m in trailing if m.role == ChatMessageRole.ASSISTANT)
                room.turn_count -= removed_turns
                await db.execute(
                    delete(ChatMessage).where(ChatMessage.id.in_([m.id for m in trailing]))
                )
                # 지운 AI 응답을 아래 커밋에 함께 기록한다. 새 턴 생성이 실패해도 이 삭제는 이미 커밋돼
                # 응답이 사라진 뒤라 기록도 남는 것이 맞다. AI 응답을 하나도 지우지 않은 편집은 세지 않는다.
                if removed_turns >= 1:
                    db.add(
                        DiscardedResponse(
                            user_id=room.user_id, chat_room_id=room.id, kind="edit", discarded_count=removed_turns
                        )
                    )

            message.content = payload.content
            await db.commit()

            async for event in _stream_new_turn(
                db,
                room,
                llm_client,
                setup,
                history,
                payload.content,
                None,
                prompt_set,
                prompt_sections,
                charge,
                session_factory,
                background_tasks,
                settlement,
            ):
                yield event
    finally:
        # 방 락 해제의 첫 자리(`send_message` 의 같은 자리 주석 참조).
        await release_room_turn_lock(turn_lock)


@router.delete("/{room_id}/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    room_id: uuid.UUID,
    message_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """개별 메시지 삭제 — 사용자/AI 메시지 모두 동일하게 지원한다. 진행 중 턴이 있는 방이면 409 — 턴 입력이던
    메시지를 지워도 응답이 그 뒤에 붙는다(`chat/turn_lock.py`)."""
    room = await _get_owned_room(db, room_id, user_id)
    async with hold_room_turn_lock(room.id):
        message = await db.get(ChatMessage, message_id)
        if message is None or message.chat_room_id != room.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
        # 지운 메시지를 요약이 덮고 있었으면 그 요약도 되감는다 — 지운 대화가 요약으로 계속 실리지 않게.
        await rewind_memory(db, room.id, (message.created_at, message.id))
        await db.delete(message)
        await db.commit()


async def _persona_names(db: AsyncSession, rooms: Sequence[ChatRoom]) -> dict[uuid.UUID, str]:
    """방들이 고른 대화 프로필의 이름을 한 번에 읽는다(방마다 읽으면 방 수만큼 쿼리가 는다)."""
    persona_ids = {room.persona_id for room in rooms if room.persona_id is not None}
    if not persona_ids:
        return {}
    return {
        persona.id: persona.name
        for persona in (await db.scalars(select(UserPersona).where(UserPersona.id.in_(persona_ids)))).all()
    }


def _last_message_preview(
    message: ChatMessage | None,
    room: ChatRoom,
    content_type: ContentType,
    content_name: str,
    default_user_name: str,
    persona_names: dict[uuid.UUID, str],
) -> str:
    """방 목록의 마지막 메시지 미리보기. 목록 화면은 방마다 다른 프로필 이름을 모르므로 작가 글의 `{{user}}`·
    `{{char}}` 를 여기서 그 방의 이름으로 바꾼다. 바꾸는 것은 모델 응답·첫 메시지(작가 글의 복사본)뿐이다 — 사용자
    메시지는 화면이 보내기 전에 이미 바꿔 저장한다. 이름이 이미지 태그로 읽히지 않게 태그를 먼저 지운다."""
    if message is None:
        return ""
    preview = strip_media_tags(message.content)
    if message.role != ChatMessageRole.ASSISTANT:
        return preview
    persona_name = persona_names.get(room.persona_id) if room.persona_id is not None else None
    return expand_author_macros(
        preview,
        user_name=resolve_user_name(persona_name, default_user_name),
        char_name=content_name if content_type == ContentType.CHARACTER else None,
    )


@router.get("")
async def list_chat_rooms(
    content_id: uuid.UUID = Query(alias="contentId"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[ChatRoomListItem]:
    rooms = await _room_siblings(db, user_id, content_id)
    if not rooms:
        return []
    content = await db.get(Content, content_id)
    assert content is not None
    detail_model = detail_model_for(content.type)
    # 방마다 고정한 버전이 다를 수 있다 — 버전별 작품명·작품 기본 이름.
    version_names: dict[uuid.UUID, tuple[str, str]] = {
        version_id: (name, default_user_name)
        for version_id, name, default_user_name in (
            await db.execute(
                select(detail_model.content_version_id, detail_model.name, detail_model.default_user_name).where(
                    detail_model.content_version_id.in_({room.content_version_id for room in rooms})
                )
            )
        ).all()
    }
    persona_names = await _persona_names(db, rooms)

    # 방당 최신 메시지 1건만 Postgres DISTINCT ON 으로 고른다 — 방들의 메시지를 전부 메모리로 끌어오면 긴 방
    # 하나가 목록 한 번에 수천 행을 읽힌다. 시각이 같으면 id 가 큰 쪽이다(턴 히스토리 정렬의 마지막,
    # `list_my_chat_rooms` 와 같은 선택).
    last_messages: dict[uuid.UUID, ChatMessage] = {
        message.chat_room_id: message
        for message in (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id.in_([room.id for room in rooms]))
                .distinct(ChatMessage.chat_room_id)
                .order_by(ChatMessage.chat_room_id, ChatMessage.created_at.desc(), ChatMessage.id.desc())
            )
        ).all()
    }

    items = []
    for ordinal, room in enumerate(rooms, start=1):
        last_message = last_messages.get(room.id)
        items.append(
            ChatRoomListItem(
                id=room.id,
                name=_display_name(room, ordinal),
                last_message_preview=_last_message_preview(
                    last_message, room, content.type, *version_names[room.content_version_id], persona_names
                ),
                created_at=room.created_at,
            )
        )
    return items


@chat_models_router.get("")
async def list_chat_models(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[ChatModelItem]:
    """이 계정이 채팅방에 고를 수 있는 모델과 턴 가격. 기본 모델(Gemini)은 언제나 있고 맨 앞이다 — 빌더 미리보기도 이 항목에서
    턴 가격을 읽는다. 상위 모델은 채팅 상위 모델 허용이 있을 때만 싣는다(모델 지정 라우트·턴 게이트와 같은 판정)."""
    allowed = await has_chat_premium_access(db, user_id)
    return [
        ChatModelItem(id=spec.id, name=spec.name, turn_cost=chat_turn_cost(spec.id))
        for spec in CHAT_MODELS
        if spec.id == DEFAULT_CHAT_MODEL or allowed
    ]


@me_router.get("/chat-rooms")
async def list_my_chat_rooms(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[MyChatRoomListItem]:
    """헤더 "내 채팅목록"용 — 콘텐츠 스코프 없이 사용자의 모든 방을 한 번에 내려준다.
    콘텐츠의 공개범위·이용제한·삭제 상태는 보지 않는다(`list_chat_rooms`도 그렇다 —
    여기서만 감추면 방 안에서는 보이는 대화가 목록에서만 사라지는 것처럼 보인다)."""
    rooms = list(
        (
            await db.scalars(
                select(ChatRoom)
                .where(ChatRoom.user_id == user_id)
                .order_by(ChatRoom.created_at.asc(), ChatRoom.id.asc())
            )
        ).all()
    )
    if not rooms:
        return []

    # "대화 N"의 N은 콘텐츠별 생성순 순번(`_room_siblings`와 같은 정렬 기준) — 위 쿼리가
    # 이미 전체를 created_at asc, id asc로 가져왔으므로, 콘텐츠별 부분열도 같은 순서를
    # 유지한다. `_room_siblings`를 방마다 호출하면 N 쿼리가 되므로 메모리에서 직접 센다.
    ordinals: dict[uuid.UUID, int] = {}
    content_room_counts: dict[uuid.UUID, int] = {}
    for room in rooms:
        content_room_counts[room.content_id] = content_room_counts.get(room.content_id, 0) + 1
        ordinals[room.id] = content_room_counts[room.content_id]

    room_ids = [room.id for room in rooms]

    # 방당 최신 메시지 1건만 Postgres DISTINCT ON 으로 가져온다 — 사용자가 지금까지 주고받은 모든
    # 메시지를 메모리로 끌어오지 않으려고(로컬 dev DB에도 한 방에 250건 이상 있다).
    # `list_chat_rooms`(위)도 같은 쿼리다.
    last_messages: dict[uuid.UUID, ChatMessage] = {
        message.chat_room_id: message
        for message in (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id.in_(room_ids))
                .distinct(ChatMessage.chat_room_id)
                .order_by(
                    ChatMessage.chat_room_id, ChatMessage.created_at.desc(), ChatMessage.id.desc()
                )
            )
        ).all()
    }

    # 작품명·썸네일은 방이 고정한 content_version_id 기준(현재 발행 버전이 아니다) —
    # list_my_favorites(content/router.py)와 같은 "type별 배치 조회 → dict 매핑" 패턴.
    content_ids = {room.content_id for room in rooms}
    contents = {
        content.id: content
        for content in (await db.scalars(select(Content).where(Content.id.in_(content_ids)))).all()
    }

    version_ids = [room.content_version_id for room in rooms]
    character_details = {
        detail.content_version_id: detail
        for detail in (
            await db.scalars(
                select(CharacterVersionDetail).where(
                    CharacterVersionDetail.content_version_id.in_(version_ids)
                )
            )
        ).all()
    }
    story_details = {
        detail.content_version_id: detail
        for detail in (
            await db.scalars(
                select(StoryVersionDetail).where(
                    StoryVersionDetail.content_version_id.in_(version_ids)
                )
            )
        ).all()
    }

    persona_names = await _persona_names(db, rooms)

    all_details: list[CharacterVersionDetail | StoryVersionDetail] = [
        *character_details.values(),
        *story_details.values(),
    ]
    thumbnail_asset_ids = {
        detail.thumbnail_asset_id for detail in all_details if detail.thumbnail_asset_id is not None
    }
    assets = {
        asset.id: asset
        for asset in (
            await db.scalars(select(Asset).where(Asset.id.in_(thumbnail_asset_ids)))
        ).all()
    }

    items: list[MyChatRoomListItem] = []
    for room in rooms:
        content = contents.get(room.content_id)
        if content is None:
            continue
        detail: CharacterVersionDetail | StoryVersionDetail | None
        if content.type == ContentType.CHARACTER:
            detail = character_details.get(room.content_version_id)
        else:
            detail = story_details.get(room.content_version_id)
        if detail is None:
            continue

        thumbnail_url: str | None = None
        if detail.thumbnail_asset_id is not None:
            asset = assets.get(detail.thumbnail_asset_id)
            if asset is not None:
                thumbnail_url = await run_in_threadpool(
                    generate_presigned_get_url, build_thumbnail_key(asset.storage_key)
                )

        last_message = last_messages.get(room.id)
        items.append(
            MyChatRoomListItem(
                id=room.id,
                name=_display_name(room, ordinals[room.id]),
                content_id=room.content_id,
                content_type=content.type,
                content_name=detail.name,
                thumbnail_url=thumbnail_url,
                last_message_preview=_last_message_preview(
                    last_message, room, content.type, detail.name, detail.default_user_name, persona_names
                ),
                last_message_at=last_message.created_at if last_message is not None else None,
                created_at=room.created_at,
            )
        )

    # (last_message_at ?? created_at) DESC -> created_at DESC -> id DESC. NULLS LAST로
    # 빈 방을 몰지 않는다 — 메시지 없는 방의 활동 시각은 생성 시각으로 폴백한다.
    items.sort(
        key=lambda item: (item.last_message_at or item.created_at, item.created_at, item.id),
        reverse=True,
    )
    return items


@router.patch("/{room_id}", dependencies=[Depends(require_legal_consent)])
async def rename_chat_room(
    room_id: uuid.UUID,
    payload: ChatRoomRenameRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomResponse:
    room = await _get_owned_room(db, room_id, user_id)
    room.name = payload.name
    await db.commit()
    return await _to_response(db, room)


@router.post("/{room_id}/reset", dependencies=[Depends(require_legal_consent)])
async def reset_chat_room(
    room_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomResponse:
    room = await _get_owned_room(db, room_id, user_id)

    # 진행 중 턴이 있는 방이면 409 — 그 턴이 초기화된 방에 응답과 낡은 판정 결과를 쓴다(`chat/turn_lock.py`).
    async with hold_room_turn_lock(room.id):
        # 요약은 지운 대화에서 나왔으므로 함께 지운다. 기억 노트는 사용자가 적은 것이라 남긴다.
        await rewind_memory(db, room.id, None)
        await db.execute(delete(ChatMessage).where(ChatMessage.chat_room_id == room.id))
        room.turn_count = 0
        room.ending_reached = False
        room.ending_entity_id = None
        room.ending_reached_at_turn = None

        setup = await _require_starting_setup(db, room)
        if setup is not None:
            await db.execute(delete(ChatRoomStat).where(ChatRoomStat.chat_room_id == room.id))
            await _seed_initial_stats(db, room, setup)

        await _insert_opening_message(db, room, setup)
        await db.commit()

    return await _to_response(db, room)


@router.post(
    "/{room_id}/pin-latest-version", dependencies=[Depends(require_legal_consent)]
)
async def pin_latest_version(
    room_id: uuid.UUID,
    message_limit: int | None = Query(None, alias="messageLimit", ge=1),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomResponse:
    """`messages`는 그대로 두고 방이 고정한
    `content_version_id`만 콘텐츠의 현재 발행 버전으로 갱신 — 이후 응답(생성/판단)부터
    새 버전이 적용된다. 새 버전에 생긴 스탯은 시작값으로 채우고 지금까지의 스탯 값은 둔다.
    버전 목록/롤백 엔드포인트는 없다(항상 최신 1건만 대상).

    화면은 이 응답으로 방 캐시를 통째로 바꾸므로, 위로 불러 둔 깊이만큼 `messageLimit` 을 넘겨 불러 둔 메시지가
    잘리지 않게 한다."""
    room = await _get_owned_room(db, room_id, user_id)
    content = await db.get(Content, room.content_id)
    assert content is not None
    if content.current_published_version_id is not None:
        room.content_version_id = content.current_published_version_id
        await seed_missing_room_stats(db, ChatRoom.id == room.id)
    await db.commit()
    return await _to_response(db, room, message_limit=message_limit)


@router.post(
    "/{room_id}/change-starting-setup",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_legal_consent)],
)
async def change_starting_setup(
    room_id: uuid.UUID,
    payload: ChangeStartingSetupRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomResponse:
    """기존 방은 그대로 두고, 선택한 시작설정으로 새
    대화방을 생성한다 — `_create_room`(`POST /chat-rooms`와 공유)이 항상 콘텐츠의 현재 발행
    버전에 고정하므로 이 엔드포인트도 동일하게 동작한다. 캐릭터 챗 대화방은 시작설정 자체가
    없으므로(room.starting_setup_entity_id is None) 400으로 거부한다."""
    room = await _get_owned_room(db, room_id, user_id)
    if room.starting_setup_entity_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="change-starting-setup is only available for story chat rooms",
        )

    content = await db.get(Content, room.content_id)
    assert content is not None
    _ensure_content_playable(content)
    # 시작설정 변경은 새 방을 만든다. 새 방 생성과 같은 이유로, 비공개 작품에서는 작가 본인만 할 수 있다.
    if not is_open_to(content, user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "CONTENT_PRIVATE"})
    setup = await _resolve_setup_for_content(db, content, payload.starting_setup_id)

    # 기본이 아니라 원래 방의 선택을 잇는다. `room.persona_id`는
    # 락 전에 읽은 값이라 그 사이 프로필 삭제로 NULL이 됐을 수 있다 — 유저 행을 잠근 뒤 컬럼
    # select로 다시 읽는다(READ COMMITTED에서 락 뒤의 새 문장은 삭제 커밋을 본다).
    # 같은 유저의 방에서 복사하므로 소유권 재검사는 필요 없다.
    await lock_user_default_persona(db, user_id)
    persona_id = await db.scalar(select(ChatRoom.persona_id).where(ChatRoom.id == room.id))
    new_room = await _create_room(db, user_id, content, setup, persona_id=persona_id)
    await db.commit()

    return await _to_response(db, new_room)


@router.put("/{room_id}/persona", dependencies=[Depends(require_legal_consent)])  # 재동의 게이트
async def set_room_persona(
    room_id: uuid.UUID,
    payload: PersonaSelectRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> RoomPersonaResponse:
    """방의 대화 프로필을 바꾼다. 다음 턴부터 반영되고
    과거 메시지는 그대로다. 🔴 방 소유(`_get_owned_room`)와 프로필 소유(`get_owned_persona`)를
    **둘 다** 본다 — 방만 보면 남의 프로필 id를 내 방에 걸 수 있다."""
    room = await _get_owned_room(db, room_id, user_id)
    await lock_user_default_persona(db, user_id)
    persona = await get_owned_persona(db, payload.persona_id, user_id) if payload.persona_id is not None else None
    room.persona_id = payload.persona_id
    await db.commit()
    return RoomPersonaResponse(persona_id=room.persona_id, persona_name=persona.name if persona is not None else None)


@router.put("/{room_id}/model", dependencies=[Depends(require_legal_consent)])  # 재동의 게이트
async def set_room_model(
    room_id: uuid.UUID,
    payload: ChatRoomModelSelectRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomModelResponse:
    """방의 글쓰기 모델을 바꾼다. 다음 턴부터 반영되고 과거 메시지는 그대로다. 진행 중인 턴은 이미 값을 낸 모델로 끝난다
    (턴 게이트의 영수증) — 그래서 턴 락을 잡지 않는다.

    기본 모델(`"gemini"`·null)은 누구나 고를 수 있다 — 허용을 거둔 뒤에도 방을 되돌릴 수 있어야 한다. 기본 모델은 빈 값으로
    저장한다(새 방과 같은 상태). 상위 모델은 채팅 상위 모델 허용(`has_chat_premium_access`)이 있어야 하고, 없으면 403
    `{"code": "CHAT_MODEL_NOT_ALLOWED"}` 하나다 — 꺼짐·명단 밖·허용 행 없음을 가르지 않는다(소설화 게이트와 같은 이유).
    고를 때 확인하는 가격은 응답의 턴 가격이고, 그 뒤 턴은 하루 1회 확인 없이 그 가격으로 차감된다."""
    room = await _get_owned_room(db, room_id, user_id)
    model = payload.model or DEFAULT_CHAT_MODEL
    if model != DEFAULT_CHAT_MODEL and not await has_chat_premium_access(db, user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "CHAT_MODEL_NOT_ALLOWED"})
    room.chat_model = None if model == DEFAULT_CHAT_MODEL else model
    await db.commit()
    return ChatRoomModelResponse(chat_model=room.chat_model, effective_chat_model=model, turn_cost=chat_turn_cost(model))


@router.post(
    "/{room_id}/acknowledge-version-upgrade", dependencies=[Depends(require_legal_consent)]
)
async def acknowledge_version_upgrade(
    room_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomResponse:
    """`GET /chat-rooms/{id}`는 순수 조회라 스스로
    플래그를 끄지 않는다 — 배너를 노출한 뒤 FE가 이 엔드포인트를 호출해야 서버가
    `version_auto_upgraded`를 false로 되돌린다(이 확인 호출이 "봤는지"의 유일한 기준점)."""
    room = await _get_owned_room(db, room_id, user_id)
    room.version_auto_upgraded = False
    await db.commit()
    return await _to_response(db, room)


async def _memory_response(db: AsyncSession, room_id: uuid.UUID) -> ChatRoomMemoryResponse:
    """기억 API 다섯 개가 같은 모양을 돌려준다. 방 행과 현재 스냅샷을 컬럼 단위로 다시 읽는다 —
    같은 요청에서 방금 UPDATE 문으로 바꾼 값이 ORM 객체에는 반영돼 있지 않을 수 있다."""
    room_row = (
        await db.execute(
            select(ChatRoom.memory_note, ChatRoom.memory_version, ChatRoom.memory_rolled_back_at).where(
                ChatRoom.id == room_id
            )
        )
    ).one()
    snapshot_row = (
        await db.execute(
            select_current_snapshot(
                room_id,
                ChatRoomMemorySnapshot.summary_text,
                ChatRoomMemorySnapshot.previous_text,
                ChatRoomMemorySnapshot.source,
                ChatRoomMemorySnapshot.updated_at,
            )
        )
    ).first()
    summary = (
        ChatRoomMemorySummary(
            text=snapshot_row.summary_text,
            source=snapshot_row.source,
            can_revert=snapshot_row.previous_text is not None,
            updated_at=snapshot_row.updated_at,
        )
        if snapshot_row is not None
        else None
    )
    return ChatRoomMemoryResponse(
        note=room_row.memory_note,
        summary=summary,
        version=room_row.memory_version,
        rolled_back_at=room_row.memory_rolled_back_at,
        limits=ChatRoomMemoryLimits(note_max_length=MEMORY_NOTE_MAX_LENGTH, summary_max_length=SUMMARY_MAX_LENGTH),
    )


@router.get("/{room_id}/memory")
async def get_chat_room_memory(
    room_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomMemoryResponse:
    """방의 기억(사용자 노트와 현재 요약). 방 상세 응답에는 싣지 않는다 — 방 상세는 자주 다시 받아
    편집 폼의 기준값을 흔든다."""
    await _get_owned_room(db, room_id, user_id)
    return await _memory_response(db, room_id)


@router.put("/{room_id}/memory/note", dependencies=[Depends(require_legal_consent)])
async def update_chat_room_memory_note(
    room_id: uuid.UUID,
    payload: ChatRoomMemoryNoteRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomMemoryResponse:
    """노트는 사용자 한 사람만 쓰는 칸이라 버전 검사 없이 덮어쓴다. 요약 버전도 올리지 않는다 —
    올리면 노트를 저장할 때마다 열려 있던 요약 편집이 409가 된다."""
    await _get_owned_room(db, room_id, user_id)
    await db.execute(update(ChatRoom).where(ChatRoom.id == room_id).values(memory_note=payload.note))
    await db.commit()
    return await _memory_response(db, room_id)


@router.delete("/{room_id}/memory/note")
async def clear_chat_room_memory_note(
    room_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomMemoryResponse:
    """노트 비우기. 자기 데이터 삭제라 약관·처리방침 재동의 전에도 열려 있다(방·메시지·대화 프로필
    삭제와 같다). 저장과 같은 전체 응답을 돌려준다."""
    await _get_owned_room(db, room_id, user_id)
    await db.execute(update(ChatRoom).where(ChatRoom.id == room_id).values(memory_note=""))
    await db.commit()
    return await _memory_response(db, room_id)


def _memory_conflict(code: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": code})


async def _lock_current_summary_for_edit(
    db: AsyncSession, room_id: uuid.UUID, version: int
) -> tuple[uuid.UUID, str, str | None]:
    """요약 편집·되돌리기의 공통 앞부분. 방 행을 먼저 잠그고(요약 접기·되감기와 같은 락) 그 뒤에
    버전과 현재 스냅샷을 읽는다 — 락 전에 읽으면 그사이 커밋된 새 요약을 못 보고 옛 행을 고친다.
    요청의 `version`이 방의 현재 값과 다르면(폼을 연 뒤 요약이 새로 접혔거나 되감겼다) 409, 고칠
    스냅샷이 없으면(첫 접기 전) 409다. 거절은 아무것도 쓰기 전에 일어나고, 버전은 호출부가 실제로
    고칠 때만 올린다."""
    current_version = await db.scalar(
        # 요약 접기·되감기의 UPDATE와 같은 강도(FOR NO KEY UPDATE) — 그 방에 메시지를 넣는 FK 검사는 막지 않는다.
        select(ChatRoom.memory_version).where(ChatRoom.id == room_id).with_for_update(key_share=True)
    )
    if current_version != version:
        raise _memory_conflict("MEMORY_VERSION_CONFLICT")
    current = (
        await db.execute(
            select_current_snapshot(
                room_id,
                ChatRoomMemorySnapshot.id,
                ChatRoomMemorySnapshot.summary_text,
                ChatRoomMemorySnapshot.previous_text,
            )
        )
    ).first()
    if current is None:
        raise _memory_conflict("MEMORY_SUMMARY_NOT_READY")
    return current.id, current.summary_text, current.previous_text


async def _bump_memory_version(db: AsyncSession, room_id: uuid.UUID) -> None:
    """요약을 바꿨으니 진행 중인 요약 접기가 결과를 버리게 한다(접기는 읽을 때의 버전으로 저장한다)."""
    await db.execute(
        update(ChatRoom).where(ChatRoom.id == room_id).values(memory_version=ChatRoom.memory_version + 1)
    )


@router.put("/{room_id}/memory/summary", dependencies=[Depends(require_legal_consent)])
async def update_chat_room_memory_summary(
    room_id: uuid.UUID,
    payload: ChatRoomMemorySummaryRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomMemoryResponse:
    """현재 요약을 사용자가 고친다. 고치기 직전 본문과 출처를 한 단계 남겨 되돌릴 수 있게 한다. 편집 폼을 연
    뒤 요약이 새로 접혔거나 대화가 되감겼으면 `version`이 달라 409다. 첫 접기 전(스냅샷 없음)에는
    고칠 요약이 없어 409다 — 404는 같은 경로의 "방 없음"과 겹친다."""
    await _get_owned_room(db, room_id, user_id)
    snapshot_id, current_text, _previous = await _lock_current_summary_for_edit(db, room_id, payload.version)
    await _bump_memory_version(db, room_id)
    await db.execute(
        update(ChatRoomMemorySnapshot)
        .where(ChatRoomMemorySnapshot.id == snapshot_id)
        .values(
            summary_text=payload.summary,
            previous_text=current_text,
            previous_source=ChatRoomMemorySnapshot.source,
            source="user",
            updated_at=func.now(),
        )
    )
    await db.commit()
    return await _memory_response(db, room_id)


@router.post("/{room_id}/memory/summary/revert", dependencies=[Depends(require_legal_consent)])
async def revert_chat_room_memory_summary(
    room_id: uuid.UUID,
    payload: ChatRoomMemoryRevertRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomMemoryResponse:
    """사용자가 고친 요약을 고치기 직전 본문과 그 출처로 한 번 되돌린다 — AI 요약을 고쳤다 되돌리면
    다시 AI 요약으로 보인다. 되돌린 뒤에는 되돌릴 것이 없다.
    AI가 새로 접은 요약은 직전 본문을 갖지 않아 되돌릴 수 없다 — 본문만 되돌리면 방금 접힌 대화가
    요약에서도 원문에서도 빠진다."""
    await _get_owned_room(db, room_id, user_id)
    snapshot_id, _current, previous_text = await _lock_current_summary_for_edit(db, room_id, payload.version)
    if previous_text is None:
        raise _memory_conflict("MEMORY_NOTHING_TO_REVERT")
    await _bump_memory_version(db, room_id)
    await db.execute(
        update(ChatRoomMemorySnapshot)
        .where(ChatRoomMemorySnapshot.id == snapshot_id)
        .values(
            summary_text=previous_text,
            source=ChatRoomMemorySnapshot.previous_source,
            previous_text=None,
            previous_source=None,
            updated_at=func.now(),
        )
    )
    await db.commit()
    return await _memory_response(db, room_id)


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_room(
    room_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """No ON DELETE CASCADE on chat_messages/chat_room_stats (apps/api/CLAUDE.md) —
    children must be deleted before the room itself."""
    room = await _get_owned_room(db, room_id, user_id)

    # 자식 목록은 탈퇴와 같은 한 곳에 있다 — 자식 테이블이 늘 때 두 경로가 함께 따라가게.
    await delete_chat_rooms(db, [room.id])
    await db.commit()


@stories_router.get("/starting-setups/{starting_setup_id}/ending-collection")
async def get_ending_collection(
    starting_setup_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[EndingCollectionItem]:
    """`starting_setup_id`는 물리적 PK(`_build_content_snapshot`의
    `startingSetupId`와 동일한 값 — `POST /chat-rooms`의 startingSetupId 관례를 따른다), 도달
    여부는 `story_ending_unlocks`를 entity_id(버전 불변)로 조인해 같은 시작설정으로
    새 대화방을 만들어도 이전 기록이 유지되게 한다."""
    setup = await db.get(StartingSetup, starting_setup_id)
    if setup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Starting setup not found")

    endings = (
        await db.scalars(
            select(Ending).where(Ending.starting_setup_id == setup.id).order_by(Ending.order)
        )
    ).all()
    if not endings:
        return []

    unlocked_entity_ids = set(
        await db.scalars(
            select(StoryEndingUnlock.ending_entity_id).where(
                StoryEndingUnlock.user_id == user_id,
                StoryEndingUnlock.starting_setup_entity_id == setup.entity_id,
            )
        )
    )

    # 도달한 엔딩의 에필로그만 칸 id 형태로 바꾸고 그 칸만 서명한다 — 도달하지 않은 엔딩은 에필로그를
    # 싣지 않으므로 그 칸 그림도 나가지 않는다.
    reached = [ending for ending in endings if ending.entity_id in unlocked_entity_ids and ending.epilogue is not None]
    epilogues, images = await normalize_texts_for_display(
        db, setup.content_version_id, [ending.epilogue for ending in reached if ending.epilogue is not None]
    )
    epilogue_by_ending = dict(zip((ending.entity_id for ending in reached), epilogues, strict=True))

    items: list[EndingCollectionItem] = []
    for ending in endings:
        epilogue = epilogue_by_ending.get(ending.entity_id)
        items.append(
            EndingCollectionItem(
                id=ending.entity_id,
                name=ending.name,
                reached=ending.entity_id in unlocked_entity_ids,
                epilogue=epilogue,
                hint=ending.hint if ending.entity_id not in unlocked_entity_ids else None,
                media_tag_images=(
                    {cell_id: images[cell_id] for cell_id in media_tag_refs(epilogue) if cell_id in images}
                    if epilogue is not None
                    else {}
                ),
            )
        )
    return items


@characters_router.get("/{id}/image-archive")
async def get_image_archive(
    id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[ImageArchiveItem]:
    """`id`는 캐릭터 콘텐츠의 물리적 PK(`GET /contents/{id}`와
    동일 관례). 등록된 이미지는 캐릭터의 현재 발행 버전(`current_published_version_id`) 기준이고,
    노출 여부는 방 단위가 아니라 `character_image_exposures(user_id, content_id, image_entity_id)`
    존재 여부로 사용자+캐릭터 단위 누적 판정한다.

    캐릭터가 아닌 작품과 이용제한·삭제된 작품은 막고, 비공개 작품은 작가 본인과 그 작품에 대화방이 있는
    사용자(공개였을 때 대화를 시작한 독자 — 자기가 본 그림을 다시 보는 곳이다)에게만 연다. 막힌 경우는 모두
    없는 캐릭터와 같은 404 다."""
    content = await db.get(Content, id)
    if (
        content is None
        or content.type != ContentType.CHARACTER
        or content.current_published_version_id is None
        or not await is_open_to_participant(db, content, user_id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    images = (
        await db.scalars(
            select(SituationalImage)
            .where(
                SituationalImage.content_version_id == content.current_published_version_id,
                # `PATCH /contents/{id}/draft`가 이미지 파일
                # 업로드 전에 image_asset_id=NULL인 행을 먼저 만들 수 있고(SituationalImage
                # docstring), 발행 검증이 그런 행을 거부하기 전에 발행된 버전에는 NULL 행이
                # 남아 있을 수 있다. 아직
                # 이미지가 없는 슬롯은 보관함에도 내보내지 않는다 — `_load_situational_candidates`의
                # 후보 필터와 같은 판단이다. register_situational_image가
                # image_asset_id/blurred_asset_id를 항상 함께 채우므로(assets/router.py) 이
                # 필터 하나로 blurred_asset_id의 non-null도 함께 보증된다.
                SituationalImage.image_asset_id.is_not(None),
            )
            .order_by(SituationalImage.order)
        )
    ).all()
    if not images:
        return []

    exposed_entity_ids = set(
        await db.scalars(
            select(CharacterImageExposure.image_entity_id).where(
                CharacterImageExposure.user_id == user_id,
                CharacterImageExposure.content_id == content.id,
            )
        )
    )

    items = []
    for image in images:
        exposed = image.entity_id in exposed_entity_ids
        asset_id = image.image_asset_id if exposed else image.blurred_asset_id
        # The query filter above guarantees both asset id columns are non-null for every
        # row reaching here — this assert only narrows the
        # type. Publish validation alone can't be relied on for it: versions published before
        # validate_character_publish started checking situational images may still hold rows
        # without an image.
        assert asset_id is not None
        asset = await db.get(Asset, asset_id)
        assert asset is not None
        image_url = await run_in_threadpool(generate_presigned_get_url, build_thumbnail_key(asset.storage_key))
        items.append(ImageArchiveItem(id=image.entity_id, exposed=exposed, image_url=image_url))
    return items


async def _cells_with_unlock_path(db: AsyncSession, version_id: uuid.UUID) -> set[uuid.UUID]:
    """대화 중 판정을 거치지 않고도 볼 수 있는 칸 — 어느 시작설정의 첫 메시지(시작상황, 없으면 프롤로그)나 어느
    엔딩의 에필로그에 나오는 칸이다. 작가 글은 이름 형태로 저장돼 있어 그 버전의 칸 id 로 정규화해서 모은다."""
    setups = (await db.scalars(select(StartingSetup).where(StartingSetup.content_version_id == version_id))).all()
    epilogues = (
        await db.scalars(
            select(Ending.epilogue)
            .join(StartingSetup, StartingSetup.id == Ending.starting_setup_id)
            .where(StartingSetup.content_version_id == version_id, Ending.epilogue.is_not(None))
        )
    ).all()
    texts = [setup.opening_message or setup.prologue for setup in setups]
    texts += [epilogue for epilogue in epilogues if epilogue is not None]
    _, referenced = await normalize_texts(db, version_id, texts)
    return referenced


def _sign_urls(storage_keys: list[str]) -> list[str]:
    return [generate_presigned_get_url(key) for key in storage_keys]


@stories_router.get("/{id}/image-archive")
async def get_story_image_archive(
    id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[StoryImageArchiveItem]:
    """스토리 미디어 북 보관함. `id` 는 스토리 콘텐츠의 물리적 PK 이고(캐릭터 보관함과 같은 관례), 칸은 현재
    발행본의 것을 축 순서(인물 → 장면)로 싣는다. 본 칸 판정은 `story_media_exposures` — 사용자+스토리 단위로
    쌓이고 칸 entity_id 라 버전이 바뀌어도 이어진다.

    대화 중 판정에서 빠진 칸 중 첫 메시지·에필로그에도 나오지 않는 칸은 볼 길이 없어 빼되, 이미 본 칸은
    작가가 나중에 판정에서 뺐어도 남긴다. 못 본 칸은 블러본만 서명한다 — 원본 키는 응답 어디에도 나가지 않는다.

    스토리가 아닌 작품과 이용제한·삭제된 작품은 막고, 비공개 작품은 작가 본인과 그 작품에 대화방이 있는
    사용자(공개였을 때 대화를 시작한 독자 — 자기가 본 그림을 다시 보는 곳이다)에게만 연다. 막힌 경우는 모두
    없는 작품과 같은 404 다."""
    content = await db.get(Content, id)
    if (
        content is None
        or content.type != ContentType.STORY
        or content.current_published_version_id is None
        or not await is_open_to_participant(db, content, user_id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found")
    version_id = content.current_published_version_id

    original_asset = aliased(Asset)
    blurred_asset = aliased(Asset)
    rows = (
        await db.execute(
            select(MediaBookCell, MediaBookPerson.name, MediaBookScene.name, original_asset, blurred_asset)
            .join(
                MediaBookPerson,
                and_(
                    MediaBookPerson.content_version_id == MediaBookCell.content_version_id,
                    MediaBookPerson.entity_id == MediaBookCell.person_entity_id,
                ),
            )
            .join(
                MediaBookScene,
                and_(
                    MediaBookScene.content_version_id == MediaBookCell.content_version_id,
                    MediaBookScene.entity_id == MediaBookCell.scene_entity_id,
                ),
            )
            .join(original_asset, original_asset.id == MediaBookCell.image_asset_id)
            .outerjoin(blurred_asset, blurred_asset.id == MediaBookCell.blurred_asset_id)
            .where(MediaBookCell.content_version_id == version_id)
            .order_by(MediaBookPerson.order, MediaBookScene.order)
        )
    ).tuples().all()
    if not rows:
        return []

    exposed_entity_ids = set(
        await db.scalars(
            select(StoryMediaExposure.cell_entity_id).where(
                StoryMediaExposure.user_id == user_id, StoryMediaExposure.content_id == content.id
            )
        )
    )
    # 작가 글을 읽어 정규화하는 비용은 판정에서 빠진 못 본 칸이 있을 때만 낸다.
    needs_unlock_path = any(cell.exclude_from_chat and cell.entity_id not in exposed_entity_ids for cell, *_ in rows)
    reachable = await _cells_with_unlock_path(db, version_id) if needs_unlock_path else set()

    visible: list[tuple[MediaBookCell, str, str, bool, Asset]] = []
    for cell, person_name, scene_name, original, blurred in rows:
        exposed = cell.entity_id in exposed_entity_ids
        if not exposed and cell.exclude_from_chat and cell.entity_id not in reachable:
            continue
        shown = original if exposed else blurred
        # 블러본은 발행이 채운다. 없는 칸을 원본으로 대신 내면 못 본 그림이 새므로 빼 둔다.
        if shown is None:
            continue
        visible.append((cell, person_name, scene_name, exposed, shown))

    urls = await run_in_threadpool(_sign_urls, [build_thumbnail_key(asset.storage_key) for *_, asset in visible])
    return [
        StoryImageArchiveItem(
            id=cell.entity_id,
            exposed=exposed,
            image_url=url,
            width=asset.width,
            height=asset.height,
            person_name=person_name,
            scene_name=scene_name if exposed else "",
            unlock_hint="" if exposed else cell.unlock_hint,
        )
        for (cell, person_name, scene_name, exposed, asset), url in zip(visible, urls, strict=True)
    ]


def _build_preview_start_state(payload: CharacterDraftPayload | StoryDraftPayload) -> PreviewSessionState:
    """First-turn state for a preview session — the same opening-message/initial-stats
    shape `_create_room`/`_insert_opening_message`/`_seed_initial_stats` build for a real
    chat room, computed directly from the unsaved draft payload instead of DB rows (there's
    no persisted `Content`/`StartingSetup` to query yet).
    A story with multiple starting setups previews its first one — the payload carries no
    startingSetupId to choose another (the requirement only asks for the formToServer payload as-is)."""
    now = datetime.now(UTC)
    if isinstance(payload, CharacterDraftPayload):
        messages = [
            ChatMessageResponse(
                id=uuid.uuid4(), role=ChatMessageRole.ASSISTANT, content=payload.intro, created_at=now
            )
        ]
        return PreviewSessionState(payload=payload, messages=messages, stats={})

    if not payload.starting_setups:
        return PreviewSessionState(payload=payload, messages=[], stats={})

    setup = payload.starting_setups[0]
    opening_text = setup.opening_message or setup.prologue
    messages = [
        ChatMessageResponse(id=uuid.uuid4(), role=ChatMessageRole.ASSISTANT, content=opening_text, created_at=now)
    ]
    stats = {str(stat.id): float(stat.initial_value) for stat in setup.stat_defs}
    return PreviewSessionState(payload=payload, messages=messages, stats=stats)


@preview_router.post(
    "", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_legal_consent)]
)
async def start_preview_session(
    payload: CharacterDraftPayload | StoryDraftPayload,
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> PreviewSessionStartResponse:
    """`payload` is whatever
    `formToServer(getValues())` produced (same shape as `PATCH /contents/{id}/draft`'s body)
    and is stored in Redis with no validation, mirroring autosave's unvalidated path."""
    state = _build_preview_start_state(payload)
    session_id = await create_preview_session(state)
    return PreviewSessionStartResponse(preview_session_id=session_id)


async def _owned_preview_session_dependency(
    id: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> PreviewSessionState:
    """미리보기 세션 접근도 `_owned_room_dependency`와 같은 이유(SSE 제너레이터 본문 안에서
    HTTPException 금지)로 평범한 Depends로 분리한다. `PreviewSessionState`엔 저장된
    user_id가 없어 실제 소유권 대조는 불가능하다 — 로그인 요구 + 추측 불가능한 세션 id 자체가
    접근 통제라는 점에서 비밀번호 재설정 토큰과 같은 처지(apps/api/CLAUDE.md 참고)."""
    state = await get_preview_session(id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview session not found")
    return state


async def _preview_prompt_set_dependency(
    state: PreviewSessionState = Depends(_owned_preview_session_dependency),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> tuple[PromptSet, list[PromptSection]]:
    """미리보기는 Gemini 로만 돌므로 그 레인의 Gemini 세트를 읽는다.

    미리보기의 DB 읽기는 요청 스코프 세션에 얹지 않는다 — `Depends`가
    세션이 아니라 값(활성 세트)을 반환하게 만들어, 세션을 짧게 열고 즉시 닫는다. 레인은
    `state.payload`의 판별 유니언 타입으로 정한다 — DB 조회도, 별도 판별자도
    필요 없다.

    캐시 히트면 `session_factory()`를 아예 호출하지 않는다 — DB 세션을 열지 않는 것이
    이 함수의 핵심이다. 캐시 미스일 때만 짧게 열고 즉시 닫은 뒤 다음 조회를
    위해 캐시를 채운다. `Depends(get_db_session)`을 쓰지 않는 이유는 미리보기 한 턴이 LLM 호출 2회 이상으로
    수십 초 걸려서다(실측) — 요청 세션에 얹은 읽기는 라우트 본문이 반납 커밋을 하기 전까지 커넥션을 쥐므로, 값만
    돌려주는 의존성은 그 세션에 기대지 않는 편이 본문의 반납 위치와 무관하게 안전하다."""
    lane = _lane_for_preview_payload(state.payload)
    cached = await get_cached_active_prompt_set(lane, model="gemini")
    if cached is not None:
        return cached
    async with session_factory() as session:
        prompt_set, sections = await load_active_prompt_set(session, lane=lane, model="gemini")
    await set_cached_active_prompt_set(lane, prompt_set, sections, model="gemini")
    return prompt_set, sections


async def _preview_persona_dependency(
    user_id: uuid.UUID = Depends(get_current_user_id),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> UserPersona | None:
    """미리보기는 작가 본인의 **기본** 프로필을 쓴다 —
    없으면 None(프로필 섹션이 빠져 프로필 기능 이전과 같다). 턴마다 읽고 `PreviewSessionState`에는 저장하지 않는다(작가가
    도중에 기본을 바꾸면 다음 턴에 반영된다). 프로필 섹션 값과 `{{user}}` 를 바꿀 이름이 둘 다 이 프로필에서 나온다.

    세션은 짧게 열고 바로 닫는다. 이 경로에도
    요청 스코프 세션이 있다 — `require_legal_consent`가 `Depends(get_db_session)`으로 열어
    트랜잭션을 시작한 채 커밋하지 않고, FastAPI는 yield 의존성을 응답 스트리밍이 끝난 뒤에
    닫는다(`fastapi/routing.py`의 `fastapi_inner_astack`). 그 트랜잭션은 라우트 본문 첫머리의
    커밋이 반납한다. 이 조회를 그 세션에 얹어도 같지만, 그러면 반납이 본문의 커밋 위치에
    기대게 된다. 짧은 세션은 의존성 해석 중에만 커넥션을 빌리고 스트리밍 전에 돌려준다 —
    본문이 어떻게 바뀌어도 그 성질이 유지되는 쪽이 이것이다.

    `charge`(차감 게이트)보다 앞에 둔다(`send_preview_message`).
    도메인 예외는 없다 — DB 장애만 예외가 되고, 그때는 차감 전에 실패한다."""
    async with session_factory() as session:
        persona: UserPersona | None = await session.scalar(
            select(UserPersona)
            .join(User, User.default_persona_id == UserPersona.id)
            .where(User.id == user_id)
        )
        return persona


async def _preview_media_book_dependency(
    state: PreviewSessionState = Depends(_owned_preview_session_dependency),
    user_id: uuid.UUID = Depends(get_current_user_id),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> dict[uuid.UUID, MediaTagImage]:
    """미리보기 페이로드 미디어 북의 칸 그림(칸 id → 원본 서명·크기). 판정 이미지와 엔딩 에필로그 태그가 쓴다.

    페이로드는 저장되지 않은 빌더 폼이라 자산 id 를 그대로 서명하면 미리보기가 남의 자산 서명기가 된다 — 요청자
    소유의 준비된 원본·생성 이미지인 칸만 맵에 넣는다. 아닌 칸(남의 자산·업로드가 끝나지 않은 자산)은 조용히
    빠진다: 판정 후보에도 에필로그 그림에도 나오지 않고 턴은 그대로 진행한다(작가가 고칠 곳은 빌더 저장 검증이
    알려 준다). 세션은 `_preview_persona_dependency` 처럼 짧게 열고 닫으며, 칸이 없으면 열지 않는다. DB 장애만
    예외가 되므로 차감 전에 실패하도록 `charge` 보다 앞에 둔다(`send_preview_message`)."""
    payload = state.payload
    if not isinstance(payload, StoryDraftPayload) or payload.media_book is None or not payload.media_book.cells:
        return {}
    asset_ids_by_cell = {cell.id: cell.image_asset_id for cell in payload.media_book.cells}
    async with session_factory() as session:
        return await sign_owned_cell_images(session, user_id, asset_ids_by_cell)


async def _validate_preview_shortcut(
    payload: ChatMessageCreateRequest,
    state: PreviewSessionState = Depends(_owned_preview_session_dependency),
) -> ShortcutDraftItem | None:
    """`_validate_shortcut`과 동일한 이유로 SSE 제너레이터 밖에 둔다. 실제 방은 DB에서
    content_version_id로 소속을 검증하지만, 미리보기는 그 자체가 payload 안의
    `shortcuts` 배열이 유일한 소속 스코프다."""
    if payload.shortcut_id is None:
        return None
    if isinstance(state.payload, StoryDraftPayload):
        shortcut = next((s for s in state.payload.shortcuts if s.id == payload.shortcut_id), None)
        if shortcut is not None:
            return shortcut
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid shortcutId")


def _preview_chat_message(message: ChatMessageResponse) -> ChatMessage:
    """`build_generation_prompt`류가 실제로 읽는 필드(role/content)만 채운 인메모리
    `ChatMessage` — DB에 저장되지 않고 프롬프트 빌더에 넘기기 위해서만 존재한다(다른
    순수함수 테스트들이 이미 쓰는 "생성자로만 채운 ORM 모델" 패턴과 동일, apps/api/CLAUDE.md)."""
    return ChatMessage(role=message.role, content=message.content)


def _preview_stat_def(item: StatDefDraftItem) -> StatDef:
    return StatDef(
        entity_id=item.id,
        name=item.name,
        description=item.description,
        min_value=item.min_value,
        max_value=item.max_value,
        initial_value=item.initial_value,
        per_turn_delta=item.per_turn_delta,
    )


def _preview_stat_rules(item: StatDefDraftItem) -> list[StatRule]:
    """초안 스탯의 규칙을 판정 빌더가 읽는 인메모리 `StatRule` 로. 배열 순서가 순서다(저장과 같다)."""
    return [
        StatRule(entity_id=rule.id, condition=rule.condition, delta=rule.delta, order=order)
        for order, rule in enumerate(item.rules)
    ]


def _preview_cells_by_name(
    payload: StoryDraftPayload, media_images: dict[uuid.UUID, MediaTagImage]
) -> dict[tuple[str, str], uuid.UUID]:
    """페이로드 미디어 북을 (인물 이름, 장면 이름) → 칸 id 로. 축이 없는 칸은 이름이 없어 빠진다(실채팅의
    `load_media_cells_by_name` 과 같은 규칙). 그림을 서명하지 못한 칸(남의 자산·준비 안 된 자산)도 빼서 그 칸의
    태그는 없는 이름처럼 지워진다 — 빈칸 자리를 남기지 않는다."""
    if payload.media_book is None:
        return {}
    people = {person.id: person.name for person in payload.media_book.people}
    scenes = {scene.id: scene.name for scene in payload.media_book.scenes}
    return {
        (people[cell.person_id], scenes[cell.scene_id]): cell.id
        for cell in payload.media_book.cells
        if cell.person_id in people and cell.scene_id in scenes and cell.id in media_images
    }


def _prepare_preview_media_cell_judgment(
    payload: StoryDraftPayload,
    media_images: dict[uuid.UUID, MediaTagImage],
    *,
    prompt_set: PromptSet,
    prompt_sections: list[PromptSection],
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
    names: PromptNames,
) -> _MediaCellJudgment | None:
    """미리보기 칸 판정 — 실채팅 `_prepare_media_cell_judgment` 의 페이로드판. 후보는 노출 제외가 아니고 그림을
    서명한 칸(요청자 소유·준비 완료 — `_preview_media_book_dependency`)이며 빌더 축 순서다. 렌더 실패는 그림만
    포기한다."""
    if payload.media_book is None:
        return None
    people = {person.id: (order, person.name) for order, person in enumerate(payload.media_book.people)}
    scenes = {scene.id: (order, scene.name) for order, scene in enumerate(payload.media_book.scenes)}
    candidates = [
        MediaCellCandidate(
            entity_id=cell.id,
            person=people[cell.person_id][1],
            scene=scenes[cell.scene_id][1],
            situation_description=cell.situation_description,
        )
        for cell in sorted(
            payload.media_book.cells, key=lambda cell: (people[cell.person_id][0], scenes[cell.scene_id][0])
        )
        if not cell.exclude_from_chat and cell.id in media_images
    ]
    if not candidates:
        return None
    try:
        prompt = build_image_judgment_prompt(
            prompt_set=prompt_set,
            sections=prompt_sections,
            scope="story",
            assistant_label=prompt_set.story_assistant_label,
            image_lines=media_cell_image_lines(candidates, names=names),
            history=history,
            user_message=user_message,
            assistant_message=assistant_message,
            names=names,
        )
    except PromptRenderError as exc:
        logger.warning("미리보기 미디어 북 칸 판정 프롬프트 렌더 실패 — 이번 턴은 그림 없이 진행한다: %s", exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        return None
    return _MediaCellJudgment(prompt=prompt, candidate_ids={cell.entity_id for cell in candidates})


def _preview_ending_reached_event(
    payload: StoryDraftPayload,
    media_images: dict[uuid.UUID, MediaTagImage],
    ending_id: uuid.UUID,
    epilogue: str | None,
) -> ChatEndingReachedEvent:
    """미리보기 엔딩 이벤트. 에필로그는 페이로드 그대로라 이름 형태 태그다 — 실채팅처럼 칸 id 형태로 바꾸고(없는
    이름은 지운다) 가리키는 칸의 그림 맵을 싣는다."""
    if not epilogue:
        return ChatEndingReachedEvent(ending_id=ending_id, epilogue=epilogue)
    epilogue_text, refs = normalize_media_tags(epilogue, _preview_cells_by_name(payload, media_images))
    return ChatEndingReachedEvent(
        ending_id=ending_id,
        epilogue=epilogue_text,
        media_tag_images={cell_id: media_images[cell_id] for cell_id in refs if cell_id in media_images},
    )


async def _stream_preview_turn(
    state: PreviewSessionState,
    llm_client: LLMClient,
    history: list[ChatMessage],
    user_content: str,
    shortcut: ShortcutDraftItem | None,
    prompt_set: PromptSet,
    prompt_sections: list[PromptSection],
    user_persona: str,
    names: PromptNames,
    # `_stream_new_turn`은 `room.user_id`를 쓰지만 `PreviewSessionState`에는 user_id가 없다
    # (`_owned_preview_session_dependency` docstring) — 그래서 여기만 인자로 받는다.
    user_id: uuid.UUID,
    # 페이로드 칸 id → 서명된 그림(`_preview_media_book_dependency`). 이 함수는 세션을 열지 않는다.
    media_images: dict[uuid.UUID, MediaTagImage],
    settlement: TurnSettlement,
) -> AsyncIterator[ChatStreamEvent]:
    """`_stream_new_turn`과 같은 순서(생성 스트리밍 → 스탯 판단 → 엔딩 판정)를 따르되
    `ChatRoom`/DB 대신 `PreviewSessionState`(Redis, 호출부가 커밋)를 직접 갱신한다. 스탯
    반영(`apply_rule_judgment`)/엔딩 규칙 평가(`evaluate_rule_list`)/턴게이트
    (`is_ending_check_due`)/엔딩 판정 순서(`_endings_to_judge`)/키워드 매칭(`match_keyword_notes`) 엔진과 SSE 이벤트 스키마는
    실제 채팅과 완전히 동일하게 재사용한다 — `ChatRoom`/`chat_room_stats` 등 방
    상태는 DB 대신 Redis 상태 갱신으로 대체했다. 프롬프트 세트(`prompt_set`/`prompt_sections`)는
    호출부(`send_preview_message`)의 `Depends`가 DB에서 값으로 읽어 넘긴 것이다 — 이
    함수 자체는 세션을 열지 않는다."""
    try:
        prompt, system_instruction, persona_rendered, _, _ = build_preview_prompt(
            state.payload,
            history,
            user_content,
            shortcut,
            prompt_set,
            prompt_sections,
            user_persona,
            state.stats,
            names,
        )
    except PromptRenderError as exc:
        # apps/api/CLAUDE.md §SSE — LLM 호출 전이므로 여기서 흡수해도 잃는 게 없다.
        logger.warning("미리보기 프롬프트 렌더 실패: %s", exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        # 🔴 처음 설계가 빠뜨렸던 환불 자리다 — 미리보기도
        # 같은 게이트를 지나므로 클로버가 깎인다. 환불은 `yield` 앞이다.
        await settlement.refund()
        yield ChatErrorEvent(message=_GENERATION_ERROR_MESSAGE)
        return

    chunks: list[str] = []
    try:
        async for token_event in _stream_generated_tokens(
            llm_client,
            prompt,
            chunks,
            system_instruction,
            prompt_set.user_label,
            # 미리보기는 DB 방이 없다(Redis 세션).
            usage=LLMCallContext(call_site="preview_generate", user_id=user_id, room_id=None),
            turn=state.turn_count + 1,
        ):
            yield token_event
    except LLMPolicyViolationError:
        # 환불하지 않는다.
        settlement.mark_settled()
        yield ChatPolicyWarningEvent(message=_policy_warning_message(persona_rendered, note_rendered=False))
        return
    except LLMClientError as exc:
        logger.warning("미리보기 메시지 생성 실패: %s", exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        # 🔴 처음 설계가 빠뜨렸던 환불 자리다.
        await settlement.refund()
        yield ChatErrorEvent(message=_GENERATION_ERROR_MESSAGE)
        return

    assistant_content = "".join(chunks)
    assistant_message = ChatMessageResponse(
        id=uuid.uuid4(), role=ChatMessageRole.ASSISTANT, content=assistant_content, created_at=datetime.now(UTC)
    )
    state.messages.append(assistant_message)
    state.turn_count += 1

    stat_change_events: list[ChatStatChangeEvent] = []
    ending_reached_event: ChatEndingReachedEvent | None = None

    # 실제 채팅(`_stream_new_turn`)과 같은 이유로 판정 실패를 여기서 흡수한다 — 미리보기는
    # `ChatRoom` 등 방 상태를 DB에 쓰지 않지만, 예외가 SSE 제너레이터 밖으로 새면 커넥션이
    # 깨지는 것은 동일하다. 스탯 판정(최초 엔딩 전만)과 칸 판정(엔딩 뒤에도)을 실채팅처럼 동시에 부른다 —
    # 이 경로엔 DB 세션이 없어 gather 앞뒤를 가를 쓰기가 없다. 노출(보관함 해금)은 기록하지 않는다.
    try:
        if isinstance(state.payload, StoryDraftPayload):
            setup = state.payload.starting_setups[0] if state.payload.starting_setups else None
            stat_request: StatJudgmentRequest | None = None
            stat_defs: list[StatDef] = []
            current_stats = dict(state.stats)
            if setup is not None and not state.ending_reached:
                stat_defs = [_preview_stat_def(stat_def) for stat_def in setup.stat_defs]
                stat_request = prepare_stat_judgment(
                    prompt_set=prompt_set,
                    sections=prompt_sections,
                    stat_defs=stat_defs,
                    rules_by_stat_id={stat_def.id: _preview_stat_rules(stat_def) for stat_def in setup.stat_defs},
                    user_message=user_content,
                    assistant_message=assistant_content,
                    names=names,
                )
            media_judgment = _prepare_preview_media_cell_judgment(
                state.payload,
                media_images,
                prompt_set=prompt_set,
                prompt_sections=prompt_sections,
                history=history,
                user_message=user_content,
                assistant_message=assistant_content,
                names=names,
            )

            updated_stats, judged_cell_id = await asyncio.gather(
                _await_stat_judgment(
                    llm_client,
                    stat_request,
                    LLMCallContext(call_site="preview_stat_judgment", user_id=user_id, room_id=None),
                    log_subject="미리보기",
                    current_stats=current_stats,
                    stat_defs=stat_defs,
                )
                if stat_request is not None
                else _no_judgment(),
                _judge_media_cell(
                    llm_client,
                    media_judgment,
                    LLMCallContext(call_site="preview_media_book_image", user_id=user_id, room_id=None),
                    log_subject="미리보기",
                )
                if media_judgment is not None
                else _no_judgment(),
            )

            judged_image = media_images.get(judged_cell_id) if judged_cell_id is not None else None
            if judged_cell_id is not None and judged_image is not None:
                assistant_message.image_id = judged_cell_id
                assistant_message.image_url = judged_image.url
                assistant_message.image_width = judged_image.width
                assistant_message.image_height = judged_image.height

            if setup is not None and updated_stats is not None:
                for stat_id, new_value in updated_stats.items():
                    if new_value != current_stats.get(stat_id):
                        stat_change_events.append(ChatStatChangeEvent(stat_id=stat_id, new_value=new_value))
                state.stats = updated_stats

                # 실채팅과 같은 순서 함수로 판정 차례·규칙 통과 엔딩의 판정 순서를 정한다.
                for ending in _endings_to_judge(
                    [
                        (
                            ending,
                            ending.id,
                            ending.priority_stat_id,
                            [preview_ending_rule_list_item(item) for item in ending.stat_rules],
                        )
                        for ending in setup.endings
                        if is_ending_check_due(state.turn_count, ending.turn_count_gate)
                    ],
                    updated_stats,
                    log_subject="미리보기",
                ):
                    ending_judgment_prompt = build_ending_judgment_prompt(
                        prompt_set=prompt_set,
                        sections=prompt_sections,
                        judgment_prompt=ending.judgment_prompt,
                        history=history,
                        user_message=user_content,
                        assistant_message=assistant_content,
                        memory_summary="",
                        names=names,
                    )
                    ending_judgment = await llm_client.generate_structured(
                        ending_judgment_prompt,
                        EndingJudgmentResult,
                        usage=LLMCallContext(call_site="preview_ending_judgment", user_id=user_id, room_id=None),
                    )
                    if not ending_judgment.triggered:
                        continue

                    state.ending_reached = True
                    ending_reached_event = _preview_ending_reached_event(
                        state.payload, media_images, ending.id, ending.epilogue
                    )
                    break
    except (LLMClientError, PromptRenderError) as exc:
        logger.warning("미리보기 판정 실패 — 이번 턴의 판정을 건너뛴다: %s", exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))

    for stat_change_event in stat_change_events:
        yield stat_change_event
    if ending_reached_event is not None:
        yield ending_reached_event

    # 미리보기는 DB 에 남기는 것이 없어 done 을 내보내는 순간이 응답 확정이다. done 뒤로 두면 done 을 받고 끊은
    # 사용자까지 환급된다.
    settlement.mark_settled()
    yield ChatDoneEvent(final_message=assistant_message)


@preview_router.post("/{id}/messages", response_class=EventSourceResponse)
async def send_preview_message(
    id: str,
    payload: ChatMessageCreateRequest,
    # send_message와 같은 이유로 시그니처 Depends
    _consent: None = Depends(require_legal_consent),
    # 미리보기 본문은 DB 를 쓰지 않는다. 그래도 받는 이유는 `require_legal_consent`·게이트가 이 요청 스코프 세션으로
    # 트랜잭션을 연 채 끝나서다 — 본문 첫머리에서 커밋해 반납하지 않으면 생성·판정 LLM 내내 커넥션을 쥔다.
    # 의존성 캐시라 그 의존성들과 같은 세션이다.
    db: AsyncSession = Depends(get_db_session),
    # 환불은 별도 트랜잭션이라 요청 세션으로는 못 한다 — 나머지 3경로도 같은 이유로 팩토리를 따로 받는다.
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    # `_stream_new_turn`은 `room.user_id`를 쓰는데 `PreviewSessionState`에는 user_id가 없어
    # (`_owned_preview_session_dependency` docstring) 이 경로만 명시적으로 받는다. 같은
    # `Depends`를 게이트·재동의가 이미 쓰고 있어 요청 스코프 캐시로 한 번만 해석된다.
    user_id: uuid.UUID = Depends(get_current_user_id),
    state: PreviewSessionState = Depends(_owned_preview_session_dependency),
    shortcut: ShortcutDraftItem | None = Depends(_validate_preview_shortcut),
    llm_client: LLMClient = Depends(get_llm_client),
    prompt_set_data: tuple[PromptSet, list[PromptSection]] = Depends(_preview_prompt_set_dependency),
    # 작가의 기본 대화 프로필. `charge`보다 앞이다.
    persona: UserPersona | None = Depends(_preview_persona_dependency),
    # 미디어 북 칸 그림(소유·준비 확인 + 서명, 아닌 칸은 뺀다). DB 장애가 차감 전에 실패하도록 `charge`보다 앞이다.
    media_images: dict[uuid.UUID, MediaTagImage] = Depends(_preview_media_book_dependency),
    # 차감 게이트(mypy가 안 잡는다, 조회·검증
    # 의존성 전부보다 뒤에 둔다 — `send_message`의 같은 자리 주석 참조). 미리보기에서 앞에
    # 두면 만료·남의 세션(404)에서 차감만 남는다.
    charge: ChatCharge = Depends(enforce_chat_rate_limit),
) -> AsyncIterator[ChatStreamEvent]:
    """미리보기 메시지 전송 SSE. `_stream_preview_turn`이
    실제 생성+판단 파이프라인을 담당한다 — `chat_rooms`/조회수/대화수 등 어떤 지표 테이블도
    이 경로에서는 전혀 건드리지 않는다(Redis의 `PreviewSessionState` 하나만 갱신). 프롬프트
    세트만은 예외다 — `_preview_prompt_set_dependency`가 캐시 히트면 DB에 닿지 않고, 미스일
    때만 짧게 연 세션으로 활성 세트를 읽는다."""
    # 정산 가드는 `send_message` 와 같다. 미리보기는 턴 락이 없어 가드 하나로 감싼다.
    settlement = TurnSettlement(charge=charge, user_id=user_id, session_factory=session_factory)
    async with settlement.guard():
        # 의존성들이 연 요청 세션 트랜잭션을 반납한다(위 `db` 자리 주석).
        await db.commit()

        prompt_set, prompt_sections = prompt_set_data
        # 실제 방과 같은 규칙으로 고른 이름 — 프로필은 작가의 기본 프로필, 작품 기본 이름은 초안 값이다.
        names = PromptNames(
            persona_name=persona.name if persona is not None else None,
            default_user_name=state.payload.default_user_name,
            char_name=state.payload.name if isinstance(state.payload, CharacterDraftPayload) else None,
        )
        history = [_preview_chat_message(message) for message in state.messages]
        state.messages.append(
            ChatMessageResponse(
                id=uuid.uuid4(), role=ChatMessageRole.USER, content=payload.content, created_at=datetime.now(UTC)
            )
        )

        async for event in _stream_preview_turn(
            state,
            llm_client,
            history,
            payload.content,
            shortcut,
            prompt_set,
            prompt_sections,
            format_persona(persona),
            names,
            user_id,
            media_images,
            settlement,
        ):
            yield event

    # 미리보기도 `require_legal_consent`가
    # `get_db_session`을 쥐고 있어 실채팅과 같은 폭발 반경을 갖는다 — 이 SET이 실패해도
    # 제너레이터를 뚫으면 안 된다. 이 시점엔 이미 `ChatDoneEvent`까지 yield된 뒤라(위 루프),
    # 실패를 알리는 이벤트를 새로 추가해도 클라이언트가 듣고 있다는 보장이 없다 — 판정 실패를
    # 흡수하는 기존 자리들(`_stream_preview_turn`의 판정 except, `prompt_set_cache.py`의 Redis
    # GET/SET)과 같은 모양으로 조용히 흡수하고 로그+모니터링으로만 남긴다. 대가: 이번 턴은
    # Redis에 반영되지 않아 다음 조회에서 사라진다.
    #
    # `ValueError`도 함께 잡는다 —
    # `update_preview_session`은 `state.model_dump_json(by_alias=True)`를 **먼저** 계산한
    # 뒤에 `redis_client.set(...)`을 부른다. 그 직렬화 실패는 `RedisError`가 아니라
    # `PydanticSerializationError`(pydantic-core, `ValueError` 서브클래스로 직접 확인)라
    # `except RedisError` 하나로는 못 잡고 그대로 제너레이터를 뚫는다. 두 실패(Redis 커맨드
    # 자체의 실패·그 앞의 직렬화 실패)는 원인이 다르지만 이 자리에서 흡수해야 할 이유는
    # 같다 — `update_preview_session` 호출 하나를 감싸는 자리라 호출 순서를 바꾸거나 함수를
    # 쪼개는 대신 타입만 넓혔다.
    try:
        await update_preview_session(id, state)
    except (RedisError, ValueError) as exc:
        logger.warning("미리보기 세션 %s 상태 저장 실패 — 이번 턴은 다음 조회에 반영되지 않는다: %s", id, exc)
        capture_dependency_failure(exc, dependency="redis")
