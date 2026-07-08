import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.sse import EventSourceResponse
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.chat.ending_rules import evaluate_rule_list, is_ending_check_due
from api.chat.keyword_notes import match_keyword_notes
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    StatJudgmentResult,
    build_ending_judgment_prompt,
    build_generation_prompt,
    build_image_judgment_prompt,
    build_stat_judgment_prompt,
    build_story_generation_prompt,
)
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
    PlayGuideResponse,
    ShortcutSnapshot,
    StatDefSnapshot,
)
from api.chat.stats import StatChange, apply_stat_changes
from api.core.s3 import generate_presigned_get_url
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
from api.db.session import get_db_session
from api.llm.client import LLMClient, LLMClientError, LLMPolicyViolationError
from api.llm.dependencies import get_llm_client
from api.session.dependencies import get_current_user_id

router = APIRouter(prefix="/chat-rooms", tags=["chat"])

# `/stories/*`, `/characters/*`는 techspec-backend-chat.md §1에 `/chat-rooms/*`와 함께 나열돼
# 있지만 URL prefix가 달라 같은 파일 안에 별도 APIRouter를 둔다 (`api/auth/router.py`의
# `me_router`와 동일 패턴).
stories_router = APIRouter(prefix="/stories", tags=["chat"])
characters_router = APIRouter(prefix="/characters", tags=["chat"])


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
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
) -> SituationalImage | None:
    """캐릭터 챗 전용 상황별 이미지 매칭(techspec-chat-character.md §1.1, techspec-backend-chat.md
    §3.1). 등록된 이미지가 없으면 판단 호출 자체를 생략한다. 응답(matchedImageEntityId)은 항상
    단수라 "동시 매칭 시 order 최상위만 발동"은 buildJudgmentPrompt의 프롬프트 지시로 처리하고,
    여기서는 그 반환값이 실제 후보 목록에 존재하는지만 방어적으로 재확인한다. 매칭된 이미지
    자체(entity_id뿐 아니라 image_asset_id도 필요, US-073의 인라인 렌더링 URL 조회용)를
    그대로 반환한다."""
    situational_images = list(
        (
            await db.scalars(
                select(SituationalImage)
                .where(SituationalImage.content_version_id == room.content_version_id)
                .order_by(SituationalImage.order)
            )
        ).all()
    )
    if not situational_images:
        return None

    judgment_prompt = build_image_judgment_prompt(
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
            ChatMessageResponse(id=m.id, role=m.role, content=m.content, created_at=m.created_at)
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


@router.post("", status_code=status.HTTP_201_CREATED)
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
    setup = await _resolve_starting_setup(db, room)
    if setup is not None:
        return PlayGuideResponse(play_guide=setup.playguide)

    detail = await db.get(CharacterVersionDetail, room.content_version_id)
    assert detail is not None
    return PlayGuideResponse(play_guide=detail.playguide)


_POLICY_WARNING_MESSAGE = "메시지 생성이 콘텐츠 정책에 의해 중단되었습니다."
_GENERATION_ERROR_MESSAGE = "메시지 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."


async def _build_prompt(
    db: AsyncSession,
    room: ChatRoom,
    setup: StartingSetup | None,
    history: list[ChatMessage],
    user_content: str,
    shortcut: Shortcut | None,
) -> str:
    """캐릭터 챗은 character_prompt+exampleDialogues로, 스토리 챗은 스토리 설정 템플릿+시작설정
    프롤로그로 생성 프롬프트를 조립한다(techspec-backend-chat.md §3.1). `send_message`/`edit_message`
    (`_stream_new_turn` 경유)와 `regenerate_message`가 공유한다."""
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
        return build_story_generation_prompt(
            prompt_template=story_detail.prompt_template,
            setting_text=story_detail.setting_text,
            development_example=story_detail.development_example,
            custom_prompt=story_detail.custom_prompt,
            prologue=setup.prologue,
            history=history,
            user_message=user_content,
            keyword_note_texts=[note.info_text for note in matched_notes],
            shortcut_prompt=shortcut.prompt if shortcut is not None else None,
        )

    detail = await db.get(CharacterVersionDetail, room.content_version_id)
    assert detail is not None
    return build_generation_prompt(
        character_prompt=detail.character_prompt,
        example_dialogues=detail.example_dialogues,
        history=history,
        user_message=user_content,
    )


async def _stream_generated_tokens(
    llm_client: LLMClient, prompt: str, chunks: list[str]
) -> AsyncIterator[ChatTokenEvent]:
    """`llm_client.generate()`의 각 델타를 그대로 relay하며 호출부가 넘긴 빈 리스트 `chunks`에
    누적한다 — 제너레이터는 반환값과 yield를 동시에 쓸 수 없어, 스트림 종료 후 조립할 전체
    텍스트를 이 out-param으로 호출부에 넘긴다."""
    async for delta in llm_client.generate(prompt):
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
) -> AsyncIterator[ChatStreamEvent]:
    """생성 + 판단(§3.1 buildJudgmentPrompt+generateStructured) + turn_count 증가까지 "새 턴
    하나"를 전부 실행한다. `send_message`(새 사용자 메시지)와 `edit_message`(수정된 메시지부터
    이어서 생성)가 공유한다 — 둘 다 실제로는 동일한 "새 턴"이고 차이는 호출부가 넘기는
    history/user_content뿐이다. 캐릭터 챗은 상황별 이미지 매칭만(US-072, 결과는 done 이벤트의
    finalMessage.imageId), 스토리 챗은 스탯 변경과 엔딩 판정만 수행한다 — 서로의 판단 단계를
    타지 않는다. 스토리 챗은 최초 엔딩 도달(room.ending_reached) 이후로는 이 판단 단계
    전체(스탯/엔딩 모두)가 중단된다(FR-41) — 메시지 생성 자체는 계속 허용.

    `regenerate_message`(같은 턴의 응답만 교체, 판단/turn_count 재실행 없음)는 이 헬퍼를 쓰지
    않는다 — 그 라우트의 docstring 참고.
    """
    prompt = await _build_prompt(db, room, setup, history, user_content, shortcut)

    chunks: list[str] = []
    try:
        async for token_event in _stream_generated_tokens(llm_client, prompt, chunks):
            yield token_event
    except LLMPolicyViolationError:
        yield ChatPolicyWarningEvent(message=_POLICY_WARNING_MESSAGE)
        return
    except LLMClientError:
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
            stat_defs=stat_defs,
            current_stats=current_stats,
            history=history,
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
                judgment_prompt=ending.judgment_prompt,
                history=history,
                user_message=user_content,
                assistant_message=assistant_content,
            )
            ending_judgment = await llm_client.generate_structured(ending_judgment_prompt, EndingJudgmentResult)
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
            history=history,
            user_message=user_content,
            assistant_message=assistant_content,
        )

    await db.commit()

    matched_image_url: str | None = None
    if matched_image is not None:
        # A room only ever matches against a published version's situational_images
        # (US-083 publish validation requires the image to be set by then).
        assert matched_image.image_asset_id is not None
        image_asset = await db.get(Asset, matched_image.image_asset_id)
        assert image_asset is not None
        matched_image_url = await run_in_threadpool(generate_presigned_get_url, image_asset.storage_key)

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
    room: ChatRoom = Depends(_owned_room_dependency),
    shortcut: Shortcut | None = Depends(_validate_shortcut),
    db: AsyncSession = Depends(get_db_session),
    llm_client: LLMClient = Depends(get_llm_client),
) -> AsyncIterator[ChatStreamEvent]:
    """text/event-stream SSE 응답 (techspec-backend-chat.md §2, §3). 실제 생성+판단 파이프라인은
    `_stream_new_turn`(이 방의 새 사용자 메시지를 커밋한 뒤 호출)이 담당한다."""
    setup = await _resolve_starting_setup(db, room)

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

    async for event in _stream_new_turn(db, room, llm_client, setup, history, payload.content, shortcut):
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
    room: ChatRoom = Depends(_owned_room_dependency),
    last_message: ChatMessage = Depends(_regeneratable_last_message_dependency),
    db: AsyncSession = Depends(get_db_session),
    llm_client: LLMClient = Depends(get_llm_client),
) -> AsyncIterator[ChatStreamEvent]:
    """마지막 AI 응답만 새로 생성해 교체한다(US-023 AC, 기존 메시지 전송과 동일한 SSE 이벤트
    스키마). `send_message`/`edit_message`와 달리 새 턴이 아니라 같은 턴의 응답을 바꾸는
    것이므로 `_stream_new_turn`을 재사용하지 않는다 — turn_count는 증가시키지 않고, 스탯/엔딩
    판단·이미지 매칭도 재실행하지 않는다(원 응답 생성 시 이미 한 번 반영됐고, 그 반영분을
    되돌릴 턴별 이력이 없어 재실행하면 오히려 중복 적용되어 부정확해진다 — 새 응답 텍스트만
    교체하는 게 이 스토리 AC가 요구하는 전부다). 생성이 실패하면(policyWarning/error) 기존
    응답을 그대로 둔다 — 대체 텍스트가 확정되기 전까지는 DB를 건드리지 않는다."""
    setup = await _resolve_starting_setup(db, room)

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
    prompt = await _build_prompt(db, room, setup, history[:-1], user_content, None)

    chunks: list[str] = []
    try:
        async for token_event in _stream_generated_tokens(llm_client, prompt, chunks):
            yield token_event
    except LLMPolicyViolationError:
        yield ChatPolicyWarningEvent(message=_POLICY_WARNING_MESSAGE)
        return
    except LLMClientError:
        yield ChatErrorEvent(message=_GENERATION_ERROR_MESSAGE)
        return

    assistant_content = "".join(chunks)
    await db.execute(delete(ChatMessage).where(ChatMessage.id == last_message.id))
    new_message = ChatMessage(chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content=assistant_content)
    db.add(new_message)
    await db.commit()

    yield ChatDoneEvent(
        final_message=ChatMessageResponse(
            id=new_message.id, role=new_message.role, content=new_message.content, created_at=new_message.created_at
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
    room: ChatRoom = Depends(_owned_room_dependency),
    message: ChatMessage = Depends(_editable_user_message_dependency),
    db: AsyncSession = Depends(get_db_session),
    llm_client: LLMClient = Depends(get_llm_client),
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
    setup = await _resolve_starting_setup(db, room)

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

    async for event in _stream_new_turn(db, room, llm_client, setup, history, payload.content, None):
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

    return [
        ChatRoomListItem(
            id=room.id,
            name=_display_name(room, ordinal),
            last_message_preview=last_messages[room.id].content,
            created_at=room.created_at,
        )
        for ordinal, room in enumerate(rooms, start=1)
    ]


@router.patch("/{room_id}")
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


@router.post("/{room_id}/reset")
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

    setup = await _resolve_starting_setup(db, room)
    if setup is not None:
        await db.execute(delete(ChatRoomStat).where(ChatRoomStat.chat_room_id == room.id))
        await _seed_initial_stats(db, room, setup)

    await _insert_opening_message(db, room, setup)
    await db.commit()

    return await _to_response(db, room)


@router.post("/{room_id}/pin-latest-version")
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


@router.post("/{room_id}/change-starting-setup", status_code=status.HTTP_201_CREATED)
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


@router.post("/{room_id}/acknowledge-version-upgrade")
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
            .where(SituationalImage.content_version_id == content.current_published_version_id)
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
        # This endpoint only lists a published version's images (assert below mirrors
        # the same US-083 publish-validation invariant as send_message's match above).
        assert asset_id is not None
        asset = await db.get(Asset, asset_id)
        assert asset is not None
        image_url = await run_in_threadpool(generate_presigned_get_url, asset.storage_key)
        items.append(ImageArchiveItem(id=image.entity_id, exposed=exposed, image_url=image_url))
    return items
