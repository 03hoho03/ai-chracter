import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.sse import EventSourceResponse
from redis.exceptions import RedisError
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from api.chat.ending_rules import evaluate_rule_list, is_ending_check_due
from api.chat.keyword_notes import match_keyword_notes
from api.chat.preview_session import create_preview_session, get_preview_session, update_preview_session
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    PromptLane,
    PromptRenderError,
    StatJudgmentResult,
    build_ending_judgment_prompt,
    build_generation_prompt,
    build_image_judgment_prompt,
    build_stat_judgment_prompt,
    build_story_generation_prompt,
    load_active_prompt_set,
    system_instruction_for,
)
from api.chat.prompt_set_cache import get_cached_active_prompt_set, set_cached_active_prompt_set
from api.chat.schemas import (
    ChangeStartingSetupRequest,
    ChatDoneEvent,
    ChatEndingReachedEvent,
    ChatErrorEvent,
    ChatMessageCreateRequest,
    ChatMessageEditRequest,
    ChatMessageResponse,
    ChatPolicyWarningEvent,
    ChatRoomContentSnapshot,
    ChatRoomCreateRequest,
    ChatRoomListItem,
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
    PlayGuideResponse,
    PreviewSessionStartResponse,
    PreviewSessionState,
    ShortcutSnapshot,
    StatDefSnapshot,
)
from api.chat.stats import StatChange, apply_stat_changes
from api.content.schemas import (
    CharacterDraftPayload,
    EndingRuleDraftItem,
    EndingRuleGroupDraftItem,
    EndingRuleListDraftItem,
    ShortcutDraftItem,
    StatDefDraftItem,
    StoryDraftPayload,
)
from api.core.config import settings
from api.core.rate_limit_gate import enforce_chat_rate_limit
from api.core.s3 import build_thumbnail_key, generate_presigned_get_url
from api.core.sentry import capture_dependency_failure
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.chat import (
    CharacterImageExposure,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomStat,
    StoryEndingUnlock,
)
from api.db.models.content import Content, ContentType
from api.db.models.media import Asset
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import (
    Ending,
    EndingRule,
    EndingRuleGroup,
    KeywordNote,
    Shortcut,
    StartingSetup,
    StatDef,
    StoryVersionDetail,
)
from api.db.session import get_db_session, get_session_factory
from api.legal.dependencies import require_legal_consent
from api.llm.client import LLMClient, LLMClientError, LLMPolicyViolationError, LLMRateLimitError
from api.llm.dependencies import get_llm_client
from api.session.dependencies import get_current_user_id

# LLM 실패(특히 429 쿼터 소진)는 화면에 "대화 품질 문제"와 구분되지 않게 보이므로 반드시
# 서버 로그에 남긴다. uvicorn은 root logger에 핸들러를 붙이지 않아 INFO는 조용히 사라지지만
# WARNING 이상은 logging.lastResort로 stderr에 찍힌다 — 이 모듈의 로그는 전부 warning 이상.
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat-rooms", tags=["chat"])

# `/stories/*`, `/characters/*`는 techspec-backend-chat.md §1에 `/chat-rooms/*`와 함께 나열돼
# 있지만 URL prefix가 달라 같은 파일 안에 별도 APIRouter를 둔다 (`api/auth/router.py`의
# `me_router`와 동일 패턴).
stories_router = APIRouter(prefix="/stories", tags=["chat"])
characters_router = APIRouter(prefix="/characters", tags=["chat"])
preview_router = APIRouter(prefix="/preview-sessions", tags=["chat"])
# `router`의 prefix가 `/chat-rooms`라 여기 얹으면 `/chat-rooms/me/...`가 되므로 별도 라우터가
# 필요하다 — 위 stories_router/characters_router와 동일 이유. `api.auth.router.me_router`가
# 이미 그 이름을 쓰므로 main.py에서 반드시 별칭으로 import한다.
me_router = APIRouter(prefix="/me", tags=["chat"])


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
    """prompt-scope-techspec.md §3-2 (PS-14 / RS-6) — 레인 선택과 빌더 선택이 **같은 값**에서
    나오게 하는 단일 판별원. `room.starting_setup_entity_id is None`(조기 반환)이 아니라
    `_require_starting_setup`의 결과를 쓴다 — 그쪽이 더 엄격하고(행의 실재까지 보고, 불일치면
    `Depends` 단계에서 400을 던진다 — sse-assert-goal-prompt.md SA-12), `_build_prompt`가
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
    """실제 채팅은 요청 스코프 `db` 세션을 이미 갖고 있으므로 그대로 재사용한다
    (prompt-db-goal-prompt.md §7 — 미리보기의 `_preview_prompt_set_dependency`와 달리
    세션을 짧게 여닫을 이유가 없다). 레인은 `_starting_setup_dependency`가 넘겨준 `setup`
    으로 정한다(PS-14) — 라우트 본문이 따로 판별하지 않는다. 캐시 히트면 `db`를 조회하지
    않고 그대로 반환한다(§8-1, 3단계). `PromptSetNotFoundError`(D-5)가 여기서 나면 SSE
    제너레이터 본문이 시작되기 전이라 정상적인 에러 응답이 된다 — 이 예외는 캐싱하지
    않는다(negative caching 금지)."""
    lane = _lane_for_setup(setup)
    cached = await get_cached_active_prompt_set(lane)
    if cached is not None:
        return cached
    prompt_set, sections = await load_active_prompt_set(db, lane=lane)
    await set_cached_active_prompt_set(lane, prompt_set, sections)
    return prompt_set, sections


# `_preview_prompt_set_dependency`는 여기 두지 않는다 — `_owned_preview_session_dependency`
# (아래, 미리보기 섹션)에 의존하는데 그 함수는 파일 뒤쪽에 정의된다. `Depends(...)`가
# 함수 정의 시점에 평가되는 기본 인자값이라, 그 함수 정의보다 앞에 두면 `NameError`가
# 난다 — 그래서 미리보기 섹션(`_owned_preview_session_dependency` 바로 아래)에 둔다.


async def _room_siblings(db: AsyncSession, user_id: uuid.UUID, content_id: uuid.UUID) -> list[ChatRoom]:
    """All of this user's rooms for one content, oldest first — the creation order
    that "대화 N" auto-numbering (AC 3) is based on."""
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
    reference (§1 원칙 4) — resolve it back to the physical row belonging to the room's
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
    """sse-assert-goal-prompt.md SA-12 — `_resolve_starting_setup`의 상류에서 "행이 정말
    없어야 하는 경우"와 "불일치로 없는 경우"를 가른다. `starting_setup_entity_id is None`은
    캐릭터 방의 정상 신호이므로 그대로 `None`을 돌려준다 — 400은 `entity_id`가 있는데 그
    행이 방이 고정한 버전에서 사라졌을 때만 던진다. 세 호출부만 이걸 쓴다(`_to_response`는
    제외 — SA-6)."""
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
    `order` 공유 시퀀스로 합쳐 재구성한다 — 엔딩 규칙 평가 엔진(`evaluate_rule_list`,
    US-061)과 §4 contentSnapshot 응답 양쪽이 이 결과를 그대로 재사용한다."""
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


async def _ending_snapshot(db: AsyncSession, ending: Ending) -> EndingSnapshot:
    return EndingSnapshot(
        id=ending.entity_id,
        name=ending.name,
        turn_count_gate=ending.turn_count_gate,
        judgment_prompt=ending.judgment_prompt,
        epilogue=ending.epilogue,
        hint=ending.hint,
        stat_rules=await _ending_rule_items(db, ending),
    )


async def _build_content_snapshot(
    db: AsyncSession, room: ChatRoom, setup: StartingSetup
) -> ChatRoomContentSnapshot:
    """techspec-content-versioning.md §2 — stats/endings는 방이 고정한 시작설정(setup) 기준,
    단축어는 작품 전역(content_version_id) 기준(techspec-db-schema.md §5)."""
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


async def _match_situational_image(
    db: AsyncSession,
    room: ChatRoom,
    llm_client: LLMClient,
    *,
    prompt_set: PromptSet,
    prompt_sections: list[PromptSection],
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
) -> SituationalImage | None:
    """캐릭터 챗 전용 상황별 이미지 매칭(techspec-chat-character.md §1.1, techspec-backend-chat.md
    §3.1). 등록된 이미지가 없으면 판단 호출 자체를 생략한다. 응답(matchedImageEntityId)은 항상
    단수라 "동시 매칭 시 order 최상위만 발동"은 buildJudgmentPrompt의 프롬프트 지시로 처리하고,
    여기서는 그 반환값이 실제 후보 목록에 존재하는지만 방어적으로 재확인한다. 매칭된 이미지
    자체(entity_id뿐 아니라 image_asset_id도 필요, US-073의 인라인 렌더링 URL 조회용)를
    그대로 반환한다.

    두 DB 호출(후보 조회·노출 이력 조회) 모두 자체적으로 `SQLAlchemyError`를 흡수한다
    (sse-assert-goal-prompt.md SA-4/N-5) — 호출부(`_stream_new_turn`)의 기존
    `except (LLMClientError, PromptRenderError)`는 DB 예외를 잡지 않아(F-6) 그대로 두면
    제너레이터를 뚫는다. 어느 쪽이 실패하든 이번 턴의 이미지 매칭 자체를 포기한다(`None`) —
    LLM 판단은 성공했는데 노출 기록만 실패한 경우도 매칭을 절반만 살려두지 않는다.

    두 DB 호출 모두 `db.begin_nested()`(SAVEPOINT)로 국소화한다(sse-assert-progress.md
    SP-126, 적대적 리뷰 결함①) — 이 함수가 불리는 시점엔 `_stream_new_turn`이 이미
    `db.add(assistant_message)`→`flush()`→`room.turn_count += 1`로 dirty 상태를 쌓아 둔
    뒤다. SAVEPOINT 없이 여기서 진짜 Postgres 실행 오류(`DBAPIError` 계열)가 나면
    트랜잭션이 aborted 상태가 되고, 이 `except`가 예외를 삼켜도 트랜잭션은 여전히
    aborted라 뒤따르는 `_stream_new_turn`의 무방비 `await db.commit()`이 그 dirty
    `room`을 autoflush하려다 그대로 부딪혀 `DBAPIError`를 던진다 — 이 함수가 막으려는
    파열이 한 자리 뒤로 미뤄질 뿐이다. SAVEPOINT로 감싸면 실패가 그 SAVEPOINT에만 갇히고
    바깥 트랜잭션(과 이미 flush된 dirty 상태)은 그대로 유효하게 남는다(SQLAlchemy 2.0.51
    `AsyncSessionTransaction.__aexit__`이 예외 시 SAVEPOINT까지만 rollback하고 재전파함을
    소스로 확인, 격리 재현으로 실측 검증도 마쳤다 — 진행 기록 참고)."""
    try:
        async with db.begin_nested():
            situational_images = list(
                (
                    await db.scalars(
                        select(SituationalImage)
                        .where(
                            SituationalImage.content_version_id == room.content_version_id,
                            # sse-assert-goal-prompt.md SA-3/N-2: `PATCH /contents/{id}/draft`가
                            # 이미지 파일 업로드 전에 image_asset_id=NULL인 행을 먼저 만들 수 있고
                            # (character.py의 SituationalImage docstring), 발행 검증은 이 필드를
                            # 보지 않아 NULL이 발행본까지 간다(F-5). 그런 후보를 판단 프롬프트에
                            # 싣지 않는다 — LLM이 존재하지 않는 이미지를 매칭할 원인을 여기서 끊는다.
                            SituationalImage.image_asset_id.is_not(None),
                        )
                        .order_by(SituationalImage.order)
                    )
                ).all()
            )
    except SQLAlchemyError as exc:
        logger.warning("대화방 %s 상황이미지 후보 조회 실패 — 이번 턴은 매칭을 건너뛴다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency="db")
        return None

    if not situational_images:
        return None

    judgment_prompt = build_image_judgment_prompt(
        prompt_set=prompt_set,
        sections=prompt_sections,
        situational_images=situational_images,
        history=history,
        user_message=user_message,
        assistant_message=assistant_message,
    )
    judgment = await llm_client.generate_structured(judgment_prompt, ImageMatchJudgmentResult)
    if judgment.matched_image_entity_id is None:
        return None

    matched = next(
        (image for image in situational_images if str(image.entity_id) == judgment.matched_image_entity_id),
        None,
    )
    if matched is None:
        return None

    try:
        async with db.begin_nested():
            existing_exposure = await db.scalar(
                select(CharacterImageExposure).where(
                    CharacterImageExposure.user_id == room.user_id,
                    CharacterImageExposure.content_id == room.content_id,
                    CharacterImageExposure.image_entity_id == matched.entity_id,
                )
            )
            if existing_exposure is None:
                db.add(
                    CharacterImageExposure(
                        user_id=room.user_id,
                        content_id=room.content_id,
                        image_entity_id=matched.entity_id,
                    )
                )
    except SQLAlchemyError as exc:
        logger.warning("대화방 %s 이미지 노출 기록 실패 — 이번 턴은 매칭을 건너뛴다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency="db")
        return None

    return matched


async def _insert_opening_message(db: AsyncSession, room: ChatRoom, setup: StartingSetup | None) -> ChatMessage:
    if setup is not None:
        opening_text = setup.opening_message or setup.prologue
    else:
        detail = await db.get(CharacterVersionDetail, room.content_version_id)
        assert detail is not None
        opening_text = detail.intro
    message = ChatMessage(chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content=opening_text)
    db.add(message)
    await db.flush()
    return message


async def _to_response(db: AsyncSession, room: ChatRoom) -> ChatRoomResponse:
    content = await db.get(Content, room.content_id)
    assert content is not None

    siblings = await _room_siblings(db, room.user_id, room.content_id)
    ordinal = next(index for index, sibling in enumerate(siblings, start=1) if sibling.id == room.id)

    messages = (
        await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.chat_room_id == room.id)
            .order_by(ChatMessage.created_at.asc())
        )
    ).all()

    setup = await _resolve_starting_setup(db, room)
    content_snapshot = None
    stats = None
    if setup is not None:
        content_snapshot = await _build_content_snapshot(db, room, setup)
        stat_rows = (
            await db.scalars(select(ChatRoomStat).where(ChatRoomStat.chat_room_id == room.id))
        ).all()
        stats = {str(row.stat_entity_id): float(row.current_value) for row in stat_rows}

    # situational-image-goal-prompt.md SI-7: 이미지가 실린 메시지들의 entity_id를 모아
    # SituationalImage·Asset을 각 1회만 조회하고 서명한다 — 메시지마다 db.get을 부르면
    # 메시지 수만큼 쿼리가 늘어난다(N+1). image_id는 있는데 해석이 안 되면(SituationalImage
    # 없음/image_asset_id None/Asset 없음) image_url만 None으로 두고 image_id는 그대로 둔다.
    image_entity_ids = {m.image_id for m in messages if m.image_id is not None}
    image_urls: dict[uuid.UUID, str] = {}
    if image_entity_ids:
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
            ChatMessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
                image_id=m.image_id,
                image_url=image_urls.get(m.image_id) if m.image_id is not None else None,
            )
            for m in messages
        ],
        content_snapshot=content_snapshot,
        latest_version_available=content.current_published_version_id != room.content_version_id,
        version_auto_upgraded=room.version_auto_upgraded,
        created_at=room.created_at,
        updated_at=room.updated_at,
    )


async def _create_room(
    db: AsyncSession, user_id: uuid.UUID, content: Content, setup: StartingSetup | None
) -> ChatRoom:
    """`POST /chat-rooms`와 `POST /chat-rooms/{id}/change-starting-setup`(US-080)가 공유하는
    방 생성 핵심 로직 — 항상 콘텐츠의 현재 발행 버전에 고정한다."""
    room = ChatRoom(
        user_id=user_id,
        content_id=content.id,
        content_version_id=content.current_published_version_id,
        starting_setup_entity_id=setup.entity_id if setup is not None else None,
    )
    db.add(room)
    await db.flush()

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


@router.post(  # consent-gate-goal-prompt.md CG-3/CG-4: 재동의 게이트
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

    room = await _create_room(db, user_id, content, setup)
    await db.commit()

    return await _to_response(db, room)


@router.get("/{room_id}")
async def get_chat_room(
    room_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomResponse:
    room = await _get_owned_room(db, room_id, user_id)
    return await _to_response(db, room)


@router.get("/{room_id}/play-guide")
async def get_play_guide(
    room_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> PlayGuideResponse:
    """방이 고정한 버전 기준으로 플레이가이드를 온디맨드 조회한다(techspec-backend-chat.md §1) —
    contentSnapshot에는 의도적으로 포함하지 않는다(techspec-content-versioning.md §2)."""
    room = await _get_owned_room(db, room_id, user_id)
    setup = await _require_starting_setup(db, room)
    if setup is not None:
        return PlayGuideResponse(play_guide=setup.playguide)

    detail = await db.get(CharacterVersionDetail, room.content_version_id)
    assert detail is not None
    return PlayGuideResponse(play_guide=detail.playguide)


_POLICY_WARNING_MESSAGE = "메시지 생성이 콘텐츠 정책에 의해 중단되었습니다."
_GENERATION_ERROR_MESSAGE = "메시지 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."


def _llm_dependency_tag(exc: LLMClientError | PromptRenderError) -> str:
    """monitoring-techspec.md MT-6: 이 파일의 생성/판정 흡수 지점 8곳이 공유하는 승격 태그
    분류다. `PromptRenderError`는 외부 의존이 아니라 우리 템플릿 결함이라 별도 태그로 갈라
    묶어 본다. Gemini 429(쿼터 소진)는 `llm/gemini.py`의 `LLMRateLimitError`(선행 조건, MT-6)로
    다른 실패와 구분한다 — 안 갈라 붙이면 승격된 이벤트가 행동 가능하지 않다."""
    if isinstance(exc, PromptRenderError):
        return "prompt_render"
    if isinstance(exc, LLMRateLimitError):
        return "gemini_rate_limit"
    return "gemini"


async def _build_prompt(
    db: AsyncSession,
    room: ChatRoom,
    setup: StartingSetup | None,
    history: list[ChatMessage],
    user_content: str,
    shortcut: Shortcut | None,
    prompt_set: PromptSet,
    prompt_sections: list[PromptSection],
) -> tuple[str, str]:
    """캐릭터 챗은 character_prompt+exampleDialogues로, 스토리 챗은 스토리 설정 템플릿+시작설정
    프롤로그로 생성 프롬프트를 조립한다(techspec-backend-chat.md §3.1). `send_message`/`edit_message`
    (`_stream_new_turn` 경유)와 `regenerate_message`가 공유한다.

    `(prompt, system_instruction)` 튜플을 돌려준다 — 스토리 챗의 L0.5 템플릿별 지시
    (`system_instruction_for`)를 고르려면 `story_detail.prompt_template`이 필요한데, 그 조회가
    이 함수 안에서만 일어나 호출부는 모른다(chat-techspec.md §4-2). 조회를 한 번 더 하는 대신
    여기서 함께 고른다."""
    if setup is not None:
        story_detail = await db.get(StoryVersionDetail, room.content_version_id)
        assert story_detail is not None
        notes = (
            await db.scalars(
                select(KeywordNote).where(
                    KeywordNote.content_version_id == room.content_version_id,
                    or_(KeywordNote.starting_setup_id.is_(None), KeywordNote.starting_setup_id == setup.id),
                )
            )
        ).all()
        matched_notes = match_keyword_notes(user_content, list(notes))
        prompt = build_story_generation_prompt(
            prompt_set=prompt_set,
            sections=prompt_sections,
            prompt_template=story_detail.prompt_template,
            setting_text=story_detail.setting_text,
            development_examples=story_detail.development_examples,
            user_goal=story_detail.user_goal,
            rules=story_detail.rules,
            custom_prompt=story_detail.custom_prompt,
            prologue=setup.prologue,
            history=history,
            user_message=user_content,
            keyword_note_texts=[note.info_text for note in matched_notes],
            shortcut_prompt=shortcut.prompt if shortcut is not None else None,
        )
        return prompt, system_instruction_for(
            prompt_sections, is_story_chat=True, template=story_detail.prompt_template
        )

    detail = await db.get(CharacterVersionDetail, room.content_version_id)
    assert detail is not None
    prompt = build_generation_prompt(
        prompt_set=prompt_set,
        sections=prompt_sections,
        character_prompt=detail.character_prompt,
        example_dialogues=detail.example_dialogues,
        history=history,
        user_message=user_content,
    )
    return prompt, system_instruction_for(prompt_sections, is_story_chat=False)


def _dump_prompt(
    *, room_id: uuid.UUID | None, turn: int, prompt: str, system_instruction: str
) -> None:
    """tasks/chat-techspec.md §3-5(D-21·D-22): 회차 재현용으로 조립된 프롬프트를 JSONL 한
    줄로 남긴다. 호출부는 `settings.prompt_dump_path is not None`일 때만 부른다.

    바닥 지시문도 함께 남긴다 — 이 런이 바꾸는 것이 바로 그것이라, 대화록만 남고 그때
    어떤 지시문이 실렸는지 모르면 회차를 나중에 설명할 수 없다."""
    record = {
        "roomId": str(room_id) if room_id is not None else None,
        "turn": turn,
        "model": settings.gemini_model_name,
        "seed": settings.gemini_seed,
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
    room_id: uuid.UUID | None,
    turn: int,
) -> AsyncIterator[ChatTokenEvent]:
    """`llm_client.generate()`의 각 델타를 그대로 relay하며 호출부가 넘긴 빈 리스트 `chunks`에
    누적한다 — 제너레이터는 반환값과 yield를 동시에 쓸 수 없어, 스트림 종료 후 조립할 전체
    텍스트를 이 out-param으로 호출부에 넘긴다.

    바닥 지시문은 호출부가 골라 넘긴다(`system_instruction_for`) — 여기서 고를 수 없다.
    스토리/캐릭터 구분이 실제 방·미리보기에서 서로 다른 값(`setup`/`payload` 타입)으로
    드러나기 때문이다. `stop_sequences`는 `user_label`에서 파생한다(prompt-db-goal-prompt.md
    §4-5) — 이 함수가 실채팅·미리보기 공용이라 한 번만 고치면 둘 다 덮인다.

    진입부에서 `settings.prompt_dump_path`가 설정돼 있으면(기본값 None, 프로덕션 방어) 조립된
    프롬프트와 그때 실린 지시문을 그 파일에 덤프한다(D-21·D-22). **덤프 실패는 절대 스트림을
    막지 않는다** — SSE 제너레이터 본문에서 새 예외가 새면 요청 스코프 DB 세션이 강제 종료돼
    무관한 다른 요청까지 500이 된다(apps/api/CLAUDE.md §SSE 스트리밍)."""
    if settings.prompt_dump_path is not None:
        try:
            _dump_prompt(
                room_id=room_id, turn=turn, prompt=prompt, system_instruction=system_instruction
            )
        except Exception:
            logger.warning("프롬프트 덤프 실패 (room=%s, turn=%s)", room_id, turn, exc_info=True)
    async for delta in llm_client.generate(prompt, system_instruction, stop_sequences=[f"\n{user_label}:"]):
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
) -> AsyncIterator[ChatStreamEvent]:
    """생성 + 판단(§3.1 buildJudgmentPrompt+generateStructured) + turn_count 증가까지 "새 턴
    하나"를 전부 실행한다. `send_message`(새 사용자 메시지)와 `edit_message`(수정된 메시지부터
    이어서 생성)가 공유한다 — 둘 다 실제로는 동일한 "새 턴"이고 차이는 호출부가 넘기는
    history/user_content뿐이다. 캐릭터 챗은 상황별 이미지 매칭만(US-072, 결과는 `chat_messages.image_id`에
    저장돼 done 이벤트의 finalMessage와 `GET /chat-rooms/{id}` 재조회 둘 다에 실린다 —
    situational-image-goal-prompt.md SI-7), 스토리 챗은 스탯 변경과 엔딩 판정만 수행한다 —
    서로의 판단 단계를 타지 않는다. 스토리 챗은 최초 엔딩 도달(room.ending_reached) 이후로는 이 판단 단계
    전체(스탯/엔딩 모두)가 중단된다(FR-41) — 메시지 생성 자체는 계속 허용.

    `regenerate_message`(같은 턴의 응답만 교체, 스탯/엔딩 판단·turn_count 재실행 없음 —
    이미지 매칭은 재실행한다, situational-image-goal-prompt.md SI-4)는 이 헬퍼를 쓰지 않는다
    — 그 라우트의 docstring 참고.
    """
    try:
        prompt, system_instruction = await _build_prompt(
            db, room, setup, history, user_content, shortcut, prompt_set, prompt_sections
        )
    except PromptRenderError as exc:
        # apps/api/CLAUDE.md §SSE: 이 예외를 여기서 흡수하지 않으면 제너레이터 본문을 뚫고
        # 나가 태스크 취소 → 커넥션 강제종료로 번진다. LLM 호출 전이므로 흡수해도 잃는
        # 게 없다 — 아직 아무 것도 스트리밍되지 않았다.
        logger.warning("대화방 %s 프롬프트 렌더 실패: %s", room.id, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
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
            room_id=room.id,
            turn=room.turn_count + 1,
        ):
            yield token_event
    except LLMPolicyViolationError:
        yield ChatPolicyWarningEvent(message=_POLICY_WARNING_MESSAGE)
        return
    except LLMClientError as exc:
        logger.warning("대화방 %s 메시지 생성 실패: %s", room.id, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        yield ChatErrorEvent(message=_GENERATION_ERROR_MESSAGE)
        return

    assistant_content = "".join(chunks)
    assistant_message = ChatMessage(
        chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content=assistant_content
    )
    db.add(assistant_message)
    await db.flush()
    room.turn_count += 1

    stat_change_events: list[ChatStatChangeEvent] = []
    ending_reached_event: ChatEndingReachedEvent | None = None
    matched_image: SituationalImage | None = None
    # 판정 단계의 LLM 실패는 반드시 이 안에서 흡수한다 — 예외가 SSE 제너레이터 밖으로 새면
    # ASGI 태스크가 취소되면서 요청 스코프 DB 세션이 강제 종료되고, 망가진 asyncpg 커넥션이
    # 풀로 돌아가 그걸 집어간 **무관한 다른 요청**이 InterfaceError로 500이 난다(부하 실측).
    # 이미 응답은 스트리밍됐고 assistant 메시지도 flush된 뒤라, 그 턴의 판정만 포기하고
    # 정상적으로 커밋 → done 이벤트까지 마무리하는 것이 실패의 폭발 반경을 그 턴에 가둔다.
    try:
        if setup is not None and not room.ending_reached:
            stat_defs = list(
                (await db.scalars(select(StatDef).where(StatDef.starting_setup_id == setup.id))).all()
            )
            stat_rows = {
                str(row.stat_entity_id): row
                for row in (
                    await db.scalars(select(ChatRoomStat).where(ChatRoomStat.chat_room_id == room.id))
                ).all()
            }
            current_stats = {stat_id: float(row.current_value) for stat_id, row in stat_rows.items()}

            judgment_prompt = build_stat_judgment_prompt(
                prompt_set=prompt_set,
                sections=prompt_sections,
                stat_defs=stat_defs,
                current_stats=current_stats,
                user_message=user_content,
                assistant_message=assistant_content,
            )
            judgment = await llm_client.generate_structured(judgment_prompt, StatJudgmentResult)
            changes = [StatChange(stat_id=c.stat_id, new_value=c.new_value) for c in judgment.stat_changes]
            updated_stats = apply_stat_changes(current_stats, changes, stat_defs)

            for stat_id, new_value in updated_stats.items():
                if new_value != current_stats.get(stat_id):
                    stat_rows[stat_id].current_value = Decimal(str(new_value))
                    stat_change_events.append(ChatStatChangeEvent(stat_id=stat_id, new_value=new_value))

            # 엔딩 판정(FR-58): 엔딩별 turn_count_gate를 넘긴 시점부터 5턴마다만 호출하고, 그 외
            # 턴은 스킵한다. endings.order가 가장 낮은(우선순위 최상위) 엔딩부터 순서대로 판정해
            # 첫 충족 엔딩에서 멈춘다(FR-61, 동시 충족 시 최상위 하나만 발동).
            endings = list(
                (
                    await db.scalars(
                        select(Ending).where(Ending.starting_setup_id == setup.id).order_by(Ending.order)
                    )
                ).all()
            )
            for ending in endings:
                if not is_ending_check_due(room.turn_count, ending.turn_count_gate):
                    continue
                ending_judgment_prompt = build_ending_judgment_prompt(
                    prompt_set=prompt_set,
                    sections=prompt_sections,
                    judgment_prompt=ending.judgment_prompt,
                    history=history,
                    user_message=user_content,
                    assistant_message=assistant_content,
                )
                ending_judgment = await llm_client.generate_structured(
                    ending_judgment_prompt, EndingJudgmentResult
                )
                if not ending_judgment.triggered:
                    continue
                rule_items = await _ending_rule_items(db, ending)
                if not evaluate_rule_list(rule_items, updated_stats):
                    continue

                room.ending_reached = True
                room.ending_entity_id = ending.entity_id
                room.ending_reached_at_turn = room.turn_count

                existing_unlock = await db.scalar(
                    select(StoryEndingUnlock).where(
                        StoryEndingUnlock.user_id == room.user_id,
                        StoryEndingUnlock.starting_setup_entity_id == setup.entity_id,
                        StoryEndingUnlock.ending_entity_id == ending.entity_id,
                    )
                )
                if existing_unlock is None:
                    db.add(
                        StoryEndingUnlock(
                            user_id=room.user_id,
                            starting_setup_entity_id=setup.entity_id,
                            ending_entity_id=ending.entity_id,
                        )
                    )
                ending_reached_event = ChatEndingReachedEvent(ending_id=ending.entity_id, epilogue=ending.epilogue)
                break
        elif setup is None:
            matched_image = await _match_situational_image(
                db,
                room,
                llm_client,
                prompt_set=prompt_set,
                prompt_sections=prompt_sections,
                history=history,
                user_message=user_content,
                assistant_message=assistant_content,
            )
    except (LLMClientError, PromptRenderError) as exc:
        logger.warning("대화방 %s 판정 실패 — 이번 턴의 판정을 건너뛴다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))

    if matched_image is not None:
        assistant_message.image_id = matched_image.entity_id

    await db.commit()

    matched_image_url: str | None = None
    if matched_image is not None:
        # sse-assert-goal-prompt.md SA-3/N-3: 매칭 필터(N-2)가 image_asset_id가 NULL인
        # 후보를 판단 프롬프트에서 걸러내지만, 그 필터를 통과한 뒤에도 `db.get(Asset, ...)`
        # 실패와 S3 presign 실패는 남는다(F-6) — 이미 db.commit() 뒤라 예외가 여기서 새면
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

    for stat_change_event in stat_change_events:
        yield stat_change_event

    if ending_reached_event is not None:
        yield ending_reached_event

    yield ChatDoneEvent(
        final_message=ChatMessageResponse(
            id=assistant_message.id,
            role=assistant_message.role,
            content=assistant_message.content,
            created_at=assistant_message.created_at,
            image_id=matched_image.entity_id if matched_image is not None else None,
            image_url=matched_image_url,
        )
    )


@router.post("/{room_id}/messages", response_class=EventSourceResponse)
async def send_message(
    payload: ChatMessageCreateRequest,
    # consent-gate-goal-prompt.md CG-4/§2-5: SSE 제너레이터라 시그니처에 Depends로 붙인다
    # (dependencies=처럼 본문 실행 전에 해석되지만, 이 파일의 `_owned_room_dependency`
    # 관례와 일관되게 시그니처 쪽을 골랐다) — 소유권 검사(room)보다 먼저 두어 존재하지
    # 않는 room_id에서도 404가 아니라 403이 먼저 뜨게 한다.
    _consent: None = Depends(require_legal_consent),
    _rate_limit: None = Depends(enforce_chat_rate_limit),  # limit-goal-prompt.md RL-1/RL-13
    room: ChatRoom = Depends(_owned_room_dependency),
    shortcut: Shortcut | None = Depends(_validate_shortcut),
    db: AsyncSession = Depends(get_db_session),
    llm_client: LLMClient = Depends(get_llm_client),
    prompt_set_data: tuple[PromptSet, list[PromptSection]] = Depends(_active_prompt_set_dependency),
    setup: StartingSetup | None = Depends(_starting_setup_dependency),
) -> AsyncIterator[ChatStreamEvent]:
    """text/event-stream SSE 응답 (techspec-backend-chat.md §2, §3). 실제 생성+판단 파이프라인은
    `_stream_new_turn`(이 방의 새 사용자 메시지를 커밋한 뒤 호출)이 담당한다."""
    prompt_set, prompt_sections = prompt_set_data

    history = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room.id)
                .order_by(ChatMessage.created_at.asc())
            )
        ).all()
    )

    # 사용자 메시지는 Gemini 호출 전에 먼저 커밋한다 — 이후 생성이 실패해도
    # 이미 저장된 사용자 메시지는 영향받지 않아야 하기 때문 (US-053 AC).
    user_message = ChatMessage(chat_room_id=room.id, role=ChatMessageRole.USER, content=payload.content)
    db.add(user_message)
    await db.commit()

    async for event in _stream_new_turn(
        db, room, llm_client, setup, history, payload.content, shortcut, prompt_set, prompt_sections
    ):
        yield event


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
                .order_by(ChatMessage.created_at.asc())
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
    # consent-gate-goal-prompt.md CG-4/§2-5: send_message와 같은 이유로 시그니처 Depends
    _consent: None = Depends(require_legal_consent),
    _rate_limit: None = Depends(enforce_chat_rate_limit),  # limit-goal-prompt.md RL-1/RL-13
    room: ChatRoom = Depends(_owned_room_dependency),
    last_message: ChatMessage = Depends(_regeneratable_last_message_dependency),
    db: AsyncSession = Depends(get_db_session),
    llm_client: LLMClient = Depends(get_llm_client),
    prompt_set_data: tuple[PromptSet, list[PromptSection]] = Depends(_active_prompt_set_dependency),
    setup: StartingSetup | None = Depends(_starting_setup_dependency),
) -> AsyncIterator[ChatStreamEvent]:
    """마지막 AI 응답만 새로 생성해 교체한다(US-023 AC, 기존 메시지 전송과 동일한 SSE 이벤트
    스키마). `send_message`/`edit_message`와 달리 새 턴이 아니라 같은 턴의 응답을 바꾸는
    것이므로 `_stream_new_turn`을 재사용하지 않는다 — turn_count는 증가시키지 않고, 스탯/엔딩
    판단은 재실행하지 않는다(원 응답 생성 시 이미 한 번 반영됐고, 그 반영분을 되돌릴 턴별
    이력이 없어 재실행하면 오히려 중복 적용되어 부정확해진다). 이미지 매칭은 재실행한다
    (situational-image-goal-prompt.md SI-4) — 노출 기록(`CharacterImageExposure`)은
    `if existing_exposure is None`으로 첫 노출만 기록해 멱등이라 재실행이 중복 적용을 만들지
    않고, 새 응답 텍스트에 맞는 이미지가 붙는다. 생성이 실패하면(policyWarning/error) 기존
    응답을 그대로 둔다 — 대체 텍스트가 확정되기 전까지는 DB를 건드리지 않는다."""
    prompt_set, prompt_sections = prompt_set_data

    history = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room.id, ChatMessage.id != last_message.id)
                .order_by(ChatMessage.created_at.asc())
            )
        ).all()
    )
    user_content = history[-1].content
    try:
        prompt, system_instruction = await _build_prompt(
            db, room, setup, history[:-1], user_content, None, prompt_set, prompt_sections
        )
    except PromptRenderError as exc:
        logger.warning("대화방 %s 재생성 프롬프트 렌더 실패: %s", room.id, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
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
            room_id=room.id,
            # 재생성은 turn_count 를 올리지 않는다 — 같은 턴의 응답을 교체하는 것이다.
            turn=room.turn_count,
        ):
            yield token_event
    except LLMPolicyViolationError:
        yield ChatPolicyWarningEvent(message=_POLICY_WARNING_MESSAGE)
        return
    except LLMClientError as exc:
        logger.warning("대화방 %s 응답 재생성 실패: %s", room.id, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        yield ChatErrorEvent(message=_GENERATION_ERROR_MESSAGE)
        return

    assistant_content = "".join(chunks)
    await db.execute(delete(ChatMessage).where(ChatMessage.id == last_message.id))
    new_message = ChatMessage(chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content=assistant_content)
    db.add(new_message)

    matched_image: SituationalImage | None = None
    # send_message와 같은 이유(§SSE)로 판정 실패를 흡수한다 — 이미 생성된 응답까지 버리지
    # 않고 그 턴의 이미지 매칭만 포기한다.
    if setup is None:
        try:
            matched_image = await _match_situational_image(
                db,
                room,
                llm_client,
                prompt_set=prompt_set,
                prompt_sections=prompt_sections,
                history=history[:-1],
                user_message=user_content,
                assistant_message=assistant_content,
            )
        except (LLMClientError, PromptRenderError) as exc:
            logger.warning("대화방 %s 재생성 이미지 매칭 실패 — 이번 재생성의 매칭을 건너뛴다: %s", room.id, exc)
            capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))

    if matched_image is not None:
        new_message.image_id = matched_image.entity_id

    await db.commit()

    matched_image_url: str | None = None
    if matched_image is not None:
        # send_message(_stream_new_turn)와 같은 이유(sse-assert-goal-prompt.md SA-3/N-3)로
        # 미러링한다 — 매칭 필터(N-2)가 image_asset_id가 NULL인 후보를 판단 프롬프트에서
        # 걸러내지만, 그 필터를 통과한 뒤에도 `db.get(Asset, ...)` 실패와 S3 presign 실패는
        # 남는다(F-6) — 이미 db.commit() 뒤라 예외가 여기서 새면 §SSE의 폭발 반경(커넥션
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

    yield ChatDoneEvent(
        final_message=ChatMessageResponse(
            id=new_message.id,
            role=new_message.role,
            content=new_message.content,
            created_at=new_message.created_at,
            image_id=matched_image.entity_id if matched_image is not None else None,
            image_url=matched_image_url,
        )
    )


async def _editable_user_message_dependency(
    message_id: uuid.UUID,
    room: ChatRoom = Depends(_owned_room_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> ChatMessage:
    """소유권 검증과 같은 이유로 별도 Depends로 분리(SSE 제너레이터 본문에서 HTTPException 금지).
    수정 대상은 반드시 이 방에 속한 사용자 메시지여야 한다 — AI 메시지 수정은 지원하지 않는다
    (US-023 AC는 "사용자 메시지 수정"만 요구)."""
    message = await db.get(ChatMessage, message_id)
    if message is None or message.chat_room_id != room.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    if message.role != ChatMessageRole.USER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only user messages can be edited")
    return message


@router.patch("/{room_id}/messages/{message_id}", response_class=EventSourceResponse)
async def edit_message(
    payload: ChatMessageEditRequest,
    # consent-gate-goal-prompt.md CG-4/§2-5: send_message와 같은 이유로 시그니처 Depends
    _consent: None = Depends(require_legal_consent),
    _rate_limit: None = Depends(enforce_chat_rate_limit),  # limit-goal-prompt.md RL-1/RL-13
    room: ChatRoom = Depends(_owned_room_dependency),
    message: ChatMessage = Depends(_editable_user_message_dependency),
    db: AsyncSession = Depends(get_db_session),
    llm_client: LLMClient = Depends(get_llm_client),
    prompt_set_data: tuple[PromptSet, list[PromptSection]] = Depends(_active_prompt_set_dependency),
    setup: StartingSetup | None = Depends(_starting_setup_dependency),
) -> AsyncIterator[ChatStreamEvent]:
    """수정된 메시지 이후의 모든 메시지를 삭제하고 수정된 내용부터 새 AI 응답을 이어서
    생성한다(US-023 AC). `send_message`와 마찬가지로 완전히 새로운 턴이라 `_stream_new_turn`
    (판단 단계 + turn_count 증가 포함)을 그대로 재사용한다 — 차이는 새 사용자 메시지를
    추가하는 대신 기존 메시지를 갱신하고, history가 그 메시지 이전까지로 잘린다는 점뿐이다.

    삭제되는 메시지 중 AI 응답 개수만큼 turn_count를 미리 되돌려둔다(그래야 `_stream_new_turn`의
    +=1과 합쳐 실제 남은 대화 길이와 일치하고, 이후 엔딩 턴게이트 판정이 어긋나지 않는다).
    다만 삭제된 턴들이 이미 반영해 둔 chat_room_stats/ending_reached 등의 상태까지 되돌리는
    건 이번 스토리 범위 밖이다 — 되돌릴 근거가 되는 턴별 변경 이력 자체가 저장되어 있지 않고
    (알려진 한계), US-023 AC도 이 롤백을 요구하지 않는다.
    """
    prompt_set, prompt_sections = prompt_set_data

    all_messages = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room.id)
                .order_by(ChatMessage.created_at.asc())
            )
        ).all()
    )
    edited_index = next(i for i, m in enumerate(all_messages) if m.id == message.id)
    history = all_messages[:edited_index]
    trailing = all_messages[edited_index + 1 :]

    if trailing:
        removed_turns = sum(1 for m in trailing if m.role == ChatMessageRole.ASSISTANT)
        room.turn_count -= removed_turns
        await db.execute(delete(ChatMessage).where(ChatMessage.id.in_([m.id for m in trailing])))

    message.content = payload.content
    await db.commit()

    async for event in _stream_new_turn(
        db, room, llm_client, setup, history, payload.content, None, prompt_set, prompt_sections
    ):
        yield event


@router.delete("/{room_id}/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    room_id: uuid.UUID,
    message_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """개별 메시지 삭제 — 사용자/AI 메시지 모두 동일하게 지원한다(US-023 AC)."""
    room = await _get_owned_room(db, room_id, user_id)
    message = await db.get(ChatMessage, message_id)
    if message is None or message.chat_room_id != room.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    await db.delete(message)
    await db.commit()


@router.get("")
async def list_chat_rooms(
    content_id: uuid.UUID = Query(alias="contentId"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[ChatRoomListItem]:
    rooms = await _room_siblings(db, user_id, content_id)
    if not rooms:
        return []

    last_messages: dict[uuid.UUID, ChatMessage] = {}
    for message in (
        await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.chat_room_id.in_(room.id for room in rooms))
            .order_by(ChatMessage.created_at.desc())
        )
    ).all():
        last_messages.setdefault(message.chat_room_id, message)

    items = []
    for ordinal, room in enumerate(rooms, start=1):
        last_message = last_messages.get(room.id)
        items.append(
            ChatRoomListItem(
                id=room.id,
                name=_display_name(room, ordinal),
                last_message_preview=last_message.content if last_message is not None else "",
                created_at=room.created_at,
            )
        )
    return items


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

    # 방당 최신 메시지 1건만 가져온다. 기존 list_chat_rooms(위)는 "전체 스캔 + setdefault"를
    # 쓰지만 그 범위는 한 콘텐츠의 방들이라 작다 — 여기서는 사용자가 지금까지 주고받은
    # 모든 메시지를 메모리로 끌어오게 되므로(로컬 dev DB에도 한 방에 250건 이상 있다)
    # 일부러 Postgres DISTINCT ON으로 바꾼다.
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
                last_message_preview=last_message.content if last_message is not None else "",
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


@router.patch("/{room_id}", dependencies=[Depends(require_legal_consent)])  # consent-gate-goal-prompt.md CG-4
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


@router.post("/{room_id}/reset", dependencies=[Depends(require_legal_consent)])  # consent-gate-goal-prompt.md CG-4
async def reset_chat_room(
    room_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomResponse:
    room = await _get_owned_room(db, room_id, user_id)

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
)  # consent-gate-goal-prompt.md CG-4
async def pin_latest_version(
    room_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomResponse:
    """US-078, techspec-content-versioning.md §3. `messages`는 그대로 두고 방이 고정한
    `content_version_id`만 콘텐츠의 현재 발행 버전으로 갱신 — 이후 응답(생성/판단)부터
    새 버전이 적용된다. 버전 목록/롤백 엔드포인트는 없다(AC 3, 항상 최신 1건만 대상)."""
    room = await _get_owned_room(db, room_id, user_id)
    content = await db.get(Content, room.content_id)
    assert content is not None
    if content.current_published_version_id is not None:
        room.content_version_id = content.current_published_version_id
    await db.commit()
    return await _to_response(db, room)


@router.post(  # consent-gate-goal-prompt.md CG-4
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
    """US-080, techspec-backend-chat.md §1. 기존 방은 그대로 두고, 선택한 시작설정으로 새
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
    setup = await _resolve_setup_for_content(db, content, payload.starting_setup_id)

    new_room = await _create_room(db, user_id, content, setup)
    await db.commit()

    return await _to_response(db, new_room)


@router.post(
    "/{room_id}/acknowledge-version-upgrade", dependencies=[Depends(require_legal_consent)]
)  # consent-gate-goal-prompt.md CG-4
async def acknowledge_version_upgrade(
    room_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoomResponse:
    """techspec-content-versioning.md §4. `GET /chat-rooms/{id}`는 순수 조회라 스스로
    플래그를 끄지 않는다 — 배너를 노출한 뒤 FE가 이 엔드포인트를 호출해야 서버가
    `version_auto_upgraded`를 false로 되돌린다(이 확인 호출이 "봤는지"의 유일한 기준점)."""
    room = await _get_owned_room(db, room_id, user_id)
    room.version_auto_upgraded = False
    await db.commit()
    return await _to_response(db, room)


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_room(
    room_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """No ON DELETE CASCADE on chat_messages/chat_room_stats (apps/api/CLAUDE.md) —
    children must be deleted before the room itself."""
    room = await _get_owned_room(db, room_id, user_id)

    await db.execute(delete(ChatRoomStat).where(ChatRoomStat.chat_room_id == room.id))
    await db.execute(delete(ChatMessage).where(ChatMessage.chat_room_id == room.id))
    await db.delete(room)
    await db.commit()


@stories_router.get("/starting-setups/{starting_setup_id}/ending-collection")
async def get_ending_collection(
    starting_setup_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[EndingCollectionItem]:
    """techspec-backend-chat.md §1. `starting_setup_id`는 물리적 PK(`_build_content_snapshot`의
    `startingSetupId`와 동일한 값 — `POST /chat-rooms`의 startingSetupId 관례를 따른다), 도달
    여부는 `story_ending_unlocks`를 entity_id(§1 원칙 4, 버전 불변)로 조인해 같은 시작설정으로
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

    return [
        EndingCollectionItem(
            id=ending.entity_id,
            name=ending.name,
            reached=ending.entity_id in unlocked_entity_ids,
            epilogue=ending.epilogue if ending.entity_id in unlocked_entity_ids else None,
            hint=ending.hint if ending.entity_id not in unlocked_entity_ids else None,
        )
        for ending in endings
    ]


@characters_router.get("/{id}/image-archive")
async def get_image_archive(
    id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[ImageArchiveItem]:
    """techspec-backend-chat.md §4. `id`는 캐릭터 콘텐츠의 물리적 PK(`GET /contents/{id}`와
    동일 관례). 등록된 이미지는 캐릭터의 현재 발행 버전(`current_published_version_id`) 기준이고,
    노출 여부는 방 단위가 아니라 `character_image_exposures(user_id, content_id, image_entity_id)`
    존재 여부로 사용자+캐릭터 단위 누적 판정한다."""
    content = await db.get(Content, id)
    if content is None or content.current_published_version_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    images = (
        await db.scalars(
            select(SituationalImage)
            .where(
                SituationalImage.content_version_id == content.current_published_version_id,
                # sse-assert-goal-prompt.md SA-4: `PATCH /contents/{id}/draft`가 이미지 파일
                # 업로드 전에 image_asset_id=NULL인 행을 먼저 만들 수 있고(SituationalImage
                # docstring), 발행 검증은 이 필드를 보지 않아 NULL이 발행본까지 간다(F-5). 아직
                # 이미지가 없는 슬롯은 보관함에도 내보내지 않는다 — `_match_situational_image`의
                # 후보 필터(N-2)와 같은 판단이다. register_situational_image가
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
        # row reaching here (sse-assert-goal-prompt.md SA-4) — this assert only narrows the
        # type. (The previous comment claimed US-083 publish validation guaranteed this;
        # that was false — validate_character_publish never looks at situational_images.)
        assert asset_id is not None
        asset = await db.get(Asset, asset_id)
        assert asset is not None
        image_url = await run_in_threadpool(generate_presigned_get_url, build_thumbnail_key(asset.storage_key))
        items.append(ImageArchiveItem(id=image.entity_id, exposed=exposed, image_url=image_url))
    return items


def _build_preview_start_state(payload: CharacterDraftPayload | StoryDraftPayload) -> PreviewSessionState:
    """First-turn state for a preview session — the same opening-message/initial-stats
    shape `_create_room`/`_insert_opening_message`/`_seed_initial_stats` build for a real
    chat room, computed directly from the unsaved draft payload instead of DB rows (there's
    no persisted `Content`/`StartingSetup` to query yet, per techspec-builder-common.md §3).
    A story with multiple starting setups previews its first one — the payload carries no
    startingSetupId to choose another (AC only asks for the formToServer payload as-is)."""
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


@preview_router.post(  # consent-gate-goal-prompt.md CG-4/CG-9
    "", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_legal_consent)]
)
async def start_preview_session(
    payload: CharacterDraftPayload | StoryDraftPayload,
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> PreviewSessionStartResponse:
    """techspec-builder-common.md §3, techspec-backend-chat.md §1. `payload` is whatever
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
    HTTPException 금지)로 평범한 Depends로 분리한다. `PreviewSessionState`(US-088)엔 저장된
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
    """prompt-db-goal-prompt.md §8-2. 미리보기는 요청 스코프 DB 세션이 없다 — `Depends`가
    세션이 아니라 값(활성 세트)을 반환하게 만들어, 세션을 짧게 열고 즉시 닫는다. 레인은
    `state.payload`의 판별 유니언 타입으로 정한다(PS-14) — DB 조회도, 별도 판별자도
    필요 없다.

    캐시 히트면 `session_factory()`를 아예 호출하지 않는다 — DB 세션을 열지 않는 것이
    이 함수의 핵심이다(3단계, §8-1). 캐시 미스일 때만 짧게 열고 즉시 닫은 뒤 다음 조회를
    위해 캐시를 채운다. `Depends(get_db_session)`을 쓰지 않는 이유는 커넥션 풀 상한(15개)
    대비 미리보기 한 턴이 LLM 호출 2회 이상으로 수십 초 걸리기 때문이다(§8-2 실측)."""
    lane = _lane_for_preview_payload(state.payload)
    cached = await get_cached_active_prompt_set(lane)
    if cached is not None:
        return cached
    async with session_factory() as session:
        prompt_set, sections = await load_active_prompt_set(session, lane=lane)
    await set_cached_active_prompt_set(lane, prompt_set, sections)
    return prompt_set, sections


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


def _preview_ending_rule_item(item: EndingRuleDraftItem) -> EndingRuleItem:
    return EndingRuleItem(
        id=item.id, stat_id=item.stat_id, operator=item.operator, threshold=item.threshold, next_op=item.next_op
    )


def _preview_ending_rule_list_item(item: EndingRuleListDraftItem) -> EndingRuleListItem:
    if isinstance(item, EndingRuleGroupDraftItem):
        return EndingRuleGroupItem(
            id=item.id, rules=[_preview_ending_rule_item(rule) for rule in item.rules], next_op=item.next_op
        )
    return _preview_ending_rule_item(item)


def _preview_keyword_notes(payload: StoryDraftPayload, setup_id: uuid.UUID | None) -> list[KeywordNote]:
    """실제 방의 `starting_setup_id IS NULL OR == 현재 setup` DB 필터(US-065)와 동일한
    스코프 규칙을 payload 안에서 그대로 적용한다."""
    return [
        KeywordNote(info_text=note.info_text, trigger_keywords=note.trigger_keywords)
        for note in payload.keyword_notes
        if note.starting_setup_id is None or note.starting_setup_id == setup_id
    ]


def _build_preview_prompt(
    payload: CharacterDraftPayload | StoryDraftPayload,
    history: list[ChatMessage],
    user_content: str,
    shortcut: ShortcutDraftItem | None,
    prompt_set: PromptSet,
    prompt_sections: list[PromptSection],
) -> str:
    """`_build_prompt`(실제 방)과 동일한 조립 규칙을 DB 조회 대신 payload 필드에서 직접
    읽어 적용한다. 스토리 draft가 시작설정을 아직 하나도 갖지 않으면(US-088과 동일한
    "미완성 상태에서도 테스트 가능" 원칙) 빈 프롤로그로 진행한다."""
    if isinstance(payload, CharacterDraftPayload):
        return build_generation_prompt(
            prompt_set=prompt_set,
            sections=prompt_sections,
            character_prompt=payload.character_prompt,
            example_dialogues=[dialogue.model_dump(by_alias=True) for dialogue in payload.example_dialogues],
            history=history,
            user_message=user_content,
        )

    setup = payload.starting_setups[0] if payload.starting_setups else None
    notes = _preview_keyword_notes(payload, setup.id if setup is not None else None)
    matched_notes = match_keyword_notes(user_content, notes)
    return build_story_generation_prompt(
        prompt_set=prompt_set,
        sections=prompt_sections,
        prompt_template=payload.prompt_template,
        setting_text=payload.setting_text,
        development_examples=[
            example.model_dump(by_alias=True) for example in payload.development_examples
        ],
        user_goal=payload.user_goal,
        rules=payload.rules,
        custom_prompt=payload.custom_prompt,
        prologue=setup.prologue if setup is not None else "",
        history=history,
        user_message=user_content,
        keyword_note_texts=[note.info_text for note in matched_notes],
        shortcut_prompt=shortcut.prompt if shortcut is not None else None,
    )


async def _stream_preview_turn(
    state: PreviewSessionState,
    llm_client: LLMClient,
    history: list[ChatMessage],
    user_content: str,
    shortcut: ShortcutDraftItem | None,
    prompt_set: PromptSet,
    prompt_sections: list[PromptSection],
) -> AsyncIterator[ChatStreamEvent]:
    """`_stream_new_turn`과 같은 순서(생성 스트리밍 → 스탯 판단 → 엔딩 판정)를 따르되
    `ChatRoom`/DB 대신 `PreviewSessionState`(Redis, 호출부가 커밋)를 직접 갱신한다. 스탯
    클램핑(`apply_stat_changes`)/엔딩 규칙 평가(`evaluate_rule_list`)/턴게이트
    (`is_ending_check_due`)/키워드 매칭(`match_keyword_notes`) 엔진과 SSE 이벤트 스키마는
    실제 채팅과 완전히 동일하게 재사용한다(US-089 AC) — `ChatRoom`/`chat_room_stats` 등 방
    상태는 DB 대신 Redis 상태 갱신으로 대체했다. 프롬프트 세트(`prompt_set`/`prompt_sections`)는
    호출부(`send_preview_message`)의 `Depends`가 DB에서 값으로 읽어 넘긴 것이다(§8-2) — 이
    함수 자체는 세션을 열지 않는다."""
    # `_build_prompt`(실제 방)와 달리 `payload`가 이미 이 스코프에 있어(DB 조회가 아니다)
    # 튜플 반환으로 우회할 필요가 없다 — template을 여기서 바로 뽑는다.
    template = state.payload.prompt_template if isinstance(state.payload, StoryDraftPayload) else None
    try:
        prompt = _build_preview_prompt(state.payload, history, user_content, shortcut, prompt_set, prompt_sections)
        system_instruction = system_instruction_for(
            prompt_sections, is_story_chat=isinstance(state.payload, StoryDraftPayload), template=template
        )
    except PromptRenderError as exc:
        # apps/api/CLAUDE.md §SSE — LLM 호출 전이므로 여기서 흡수해도 잃는 게 없다.
        logger.warning("미리보기 프롬프트 렌더 실패: %s", exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
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
            room_id=None,
            turn=state.turn_count + 1,
        ):
            yield token_event
    except LLMPolicyViolationError:
        yield ChatPolicyWarningEvent(message=_POLICY_WARNING_MESSAGE)
        return
    except LLMClientError as exc:
        logger.warning("미리보기 메시지 생성 실패: %s", exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
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
    # 깨지는 것은 동일하다.
    try:
        if (
            isinstance(state.payload, StoryDraftPayload)
            and not state.ending_reached
            and state.payload.starting_setups
        ):
            setup = state.payload.starting_setups[0]
            stat_defs = [_preview_stat_def(stat_def) for stat_def in setup.stat_defs]
            current_stats = dict(state.stats)

            judgment_prompt = build_stat_judgment_prompt(
                prompt_set=prompt_set,
                sections=prompt_sections,
                stat_defs=stat_defs,
                current_stats=current_stats,
                user_message=user_content,
                assistant_message=assistant_content,
            )
            judgment = await llm_client.generate_structured(judgment_prompt, StatJudgmentResult)
            changes = [StatChange(stat_id=c.stat_id, new_value=c.new_value) for c in judgment.stat_changes]
            updated_stats = apply_stat_changes(current_stats, changes, stat_defs)

            for stat_id, new_value in updated_stats.items():
                if new_value != current_stats.get(stat_id):
                    stat_change_events.append(ChatStatChangeEvent(stat_id=stat_id, new_value=new_value))
            state.stats = updated_stats

            for ending in setup.endings:
                if not is_ending_check_due(state.turn_count, ending.turn_count_gate):
                    continue
                ending_judgment_prompt = build_ending_judgment_prompt(
                    prompt_set=prompt_set,
                    sections=prompt_sections,
                    judgment_prompt=ending.judgment_prompt,
                    history=history,
                    user_message=user_content,
                    assistant_message=assistant_content,
                )
                ending_judgment = await llm_client.generate_structured(
                    ending_judgment_prompt, EndingJudgmentResult
                )
                if not ending_judgment.triggered:
                    continue
                rule_items: list[EndingRuleListItem] = [
                    _preview_ending_rule_list_item(item) for item in ending.stat_rules
                ]
                if not evaluate_rule_list(rule_items, updated_stats):
                    continue

                state.ending_reached = True
                ending_reached_event = ChatEndingReachedEvent(ending_id=ending.id, epilogue=ending.epilogue)
                break
    except (LLMClientError, PromptRenderError) as exc:
        logger.warning("미리보기 판정 실패 — 이번 턴의 판정을 건너뛴다: %s", exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))

    for stat_change_event in stat_change_events:
        yield stat_change_event
    if ending_reached_event is not None:
        yield ending_reached_event

    yield ChatDoneEvent(final_message=assistant_message)


@preview_router.post("/{id}/messages", response_class=EventSourceResponse)
async def send_preview_message(
    id: str,
    payload: ChatMessageCreateRequest,
    # consent-gate-goal-prompt.md CG-4/CG-9/§2-5: send_message와 같은 이유로 시그니처 Depends
    _consent: None = Depends(require_legal_consent),
    _rate_limit: None = Depends(enforce_chat_rate_limit),  # limit-goal-prompt.md RL-1/RL-13
    state: PreviewSessionState = Depends(_owned_preview_session_dependency),
    shortcut: ShortcutDraftItem | None = Depends(_validate_preview_shortcut),
    llm_client: LLMClient = Depends(get_llm_client),
    prompt_set_data: tuple[PromptSet, list[PromptSection]] = Depends(_preview_prompt_set_dependency),
) -> AsyncIterator[ChatStreamEvent]:
    """미리보기 메시지 전송 SSE (US-089, techspec-backend-chat.md §1). `_stream_preview_turn`이
    실제 생성+판단 파이프라인을 담당한다 — `chat_rooms`/조회수/대화수 등 어떤 지표 테이블도
    이 경로에서는 전혀 건드리지 않는다(Redis의 `PreviewSessionState` 하나만 갱신). 프롬프트
    세트만은 예외다 — `_preview_prompt_set_dependency`가 캐시 히트면 DB에 닿지 않고, 미스일
    때만 짧게 연 세션으로 활성 세트를 읽는다(§8-2)."""
    prompt_set, prompt_sections = prompt_set_data
    history = [_preview_chat_message(message) for message in state.messages]
    state.messages.append(
        ChatMessageResponse(
            id=uuid.uuid4(), role=ChatMessageRole.USER, content=payload.content, created_at=datetime.now(UTC)
        )
    )

    async for event in _stream_preview_turn(
        state, llm_client, history, payload.content, shortcut, prompt_set, prompt_sections
    ):
        yield event

    # sse-assert-goal-prompt.md SA-4/N-4: 미리보기도 `require_legal_consent`가
    # `get_db_session`을 쥐고 있어 실채팅과 같은 폭발 반경을 갖는다(F-6) — 이 SET이 실패해도
    # 제너레이터를 뚫으면 안 된다. 이 시점엔 이미 `ChatDoneEvent`까지 yield된 뒤라(위 루프),
    # 실패를 알리는 이벤트를 새로 추가해도 클라이언트가 듣고 있다는 보장이 없다 — 판정 실패를
    # 흡수하는 기존 자리들(`_stream_preview_turn`의 판정 except, `prompt_set_cache.py`의 Redis
    # GET/SET)과 같은 모양으로 조용히 흡수하고 로그+모니터링으로만 남긴다. 대가: 이번 턴은
    # Redis에 반영되지 않아 다음 조회에서 사라진다(sse-assert-progress.md CP-4 기록 참고).
    #
    # `ValueError`도 함께 잡는다(sse-assert-progress.md SP-129, 적대적 리뷰 결함②) —
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
