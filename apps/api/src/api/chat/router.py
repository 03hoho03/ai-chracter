import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.schemas import (
    ChatMessageResponse,
    ChatRoomCreateRequest,
    ChatRoomListItem,
    ChatRoomRenameRequest,
    ChatRoomResponse,
)
from api.db.models.character import CharacterVersionDetail
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom, ChatRoomStat
from api.db.models.content import Content, ContentType
from api.db.session import get_db_session
from api.session.dependencies import get_current_user_id

router = APIRouter(prefix="/chat-rooms", tags=["chat"])


async def _get_owned_room(db: AsyncSession, room_id: uuid.UUID, user_id: uuid.UUID) -> ChatRoom:
    room = await db.get(ChatRoom, room_id)
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat room not found")
    if room.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the chat room owner")
    return room


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


async def _insert_opening_message(db: AsyncSession, room: ChatRoom) -> ChatMessage:
    detail = await db.get(CharacterVersionDetail, room.content_version_id)
    assert detail is not None
    message = ChatMessage(chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content=detail.intro)
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

    return ChatRoomResponse(
        id=room.id,
        content_id=room.content_id,
        content_type=content.type,
        name=_display_name(room, ordinal),
        turn_count=room.turn_count,
        ending_reached=room.ending_reached,
        messages=[
            ChatMessageResponse(id=m.id, role=m.role, content=m.content, created_at=m.created_at)
            for m in messages
        ],
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
    if content.type != ContentType.CHARACTER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content type mismatch")

    room = ChatRoom(
        user_id=user_id,
        content_id=content.id,
        content_version_id=content.current_published_version_id,
    )
    db.add(room)
    await db.flush()

    await _insert_opening_message(db, room)
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

    await _insert_opening_message(db, room)
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
