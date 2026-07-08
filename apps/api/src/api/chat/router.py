import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.sse import EventSourceResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import (
    StatJudgmentResult,
    build_generation_prompt,
    build_stat_judgment_prompt,
    build_story_generation_prompt,
)
from api.chat.schemas import (
    ChatDoneEvent,
    ChatErrorEvent,
    ChatMessageCreateRequest,
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
    EndingRuleGroupItem,
    EndingRuleItem,
    EndingRuleListItem,
    EndingSnapshot,
    ShortcutSnapshot,
    StatDefSnapshot,
)
from api.chat.stats import StatChange, apply_stat_changes
from api.db.models.character import CharacterVersionDetail
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom, ChatRoomStat
from api.db.models.content import Content, ContentType
from api.db.models.story import (
    Ending,
    EndingRule,
    EndingRuleGroup,
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


async def _ending_snapshot(db: AsyncSession, ending: Ending) -> EndingSnapshot:
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

    return EndingSnapshot(
        id=ending.entity_id,
        name=ending.name,
        turn_count_gate=ending.turn_count_gate,
        judgment_prompt=ending.judgment_prompt,
        epilogue=ending.epilogue,
        hint=ending.hint,
        stat_rules=[item for _, item in items],
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
    )


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
        setup = await db.scalar(
            select(StartingSetup).where(
                StartingSetup.id == payload.starting_setup_id,
                StartingSetup.content_version_id == content.current_published_version_id,
            )
        )
        if setup is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid startingSetupId")

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


@router.post("/{room_id}/messages", response_class=EventSourceResponse)
async def send_message(
    payload: ChatMessageCreateRequest,
    room: ChatRoom = Depends(_owned_room_dependency),
    db: AsyncSession = Depends(get_db_session),
    llm_client: LLMClient = Depends(get_llm_client),
) -> AsyncIterator[ChatStreamEvent]:
    """text/event-stream SSE 응답 (techspec-backend-chat.md §2, §3).

    캐릭터 챗은 character_prompt+exampleDialogues로, 스토리 챗은 스토리 설정 템플릿+시작설정
    프롤로그로 생성 프롬프트를 조립한다(§3.1). 스토리 챗은 생성 완료 후 스탯 변경 판단
    (§3.1 buildJudgmentPrompt+generateStructured)을 매 턴 추가로 호출한다 — 캐릭터 챗에는
    이 판단 단계가 없다. 엔딩 판정은 US-061/062 범위라 아직 없다.
    """
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

    if setup is not None:
        story_detail = await db.get(StoryVersionDetail, room.content_version_id)
        assert story_detail is not None
        prompt = build_story_generation_prompt(
            prompt_template=story_detail.prompt_template,
            setting_text=story_detail.setting_text,
            development_example=story_detail.development_example,
            custom_prompt=story_detail.custom_prompt,
            prologue=setup.prologue,
            history=history,
            user_message=payload.content,
        )
    else:
        detail = await db.get(CharacterVersionDetail, room.content_version_id)
        assert detail is not None
        prompt = build_generation_prompt(
            character_prompt=detail.character_prompt,
            example_dialogues=detail.example_dialogues,
            history=history,
            user_message=payload.content,
        )

    chunks: list[str] = []
    try:
        async for delta in llm_client.generate(prompt):
            chunks.append(delta)
            yield ChatTokenEvent(delta=delta)
    except LLMPolicyViolationError:
        yield ChatPolicyWarningEvent(message="메시지 생성이 콘텐츠 정책에 의해 중단되었습니다.")
        return
    except LLMClientError:
        yield ChatErrorEvent(message="메시지 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
        return

    assistant_content = "".join(chunks)
    assistant_message = ChatMessage(
        chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content=assistant_content
    )
    db.add(assistant_message)
    await db.flush()
    room.turn_count += 1

    stat_change_events: list[ChatStatChangeEvent] = []
    if setup is not None:
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
            user_message=payload.content,
            assistant_message=assistant_content,
        )
        judgment = await llm_client.generate_structured(judgment_prompt, StatJudgmentResult)
        changes = [StatChange(stat_id=c.stat_id, new_value=c.new_value) for c in judgment.stat_changes]
        updated_stats = apply_stat_changes(current_stats, changes, stat_defs)

        for stat_id, new_value in updated_stats.items():
            if new_value != current_stats.get(stat_id):
                stat_rows[stat_id].current_value = Decimal(str(new_value))
                stat_change_events.append(ChatStatChangeEvent(stat_id=stat_id, new_value=new_value))

    await db.commit()

    for stat_change_event in stat_change_events:
        yield stat_change_event

    yield ChatDoneEvent(
        final_message=ChatMessageResponse(
            id=assistant_message.id,
            role=assistant_message.role,
            content=assistant_message.content,
            created_at=assistant_message.created_at,
        )
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
