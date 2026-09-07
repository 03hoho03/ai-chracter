import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import AdminChatMessageItem, AdminChatMessagesResponse, AdminChatRoomViewRequest
from api.db.models.chat import ChatMessage, ChatRoom
from api.db.session import get_db_session

router = APIRouter(tags=["admin"])

# techspec.md §4-5: 최초 열람은 페이지네이션 없이 고정 100개.
CHAT_VIEW_MESSAGE_LIMIT = 100

# 더보기(GET)의 기본/상한. 최초 열람(100개)보다 작은 단위로 이어 보는 용도라 기본값은
# 그 절반으로 잡았고, 상한은 최초 열람 크기(100)를 넘지 않게 맞춰 한 번의 쿼리가 항상
# `chat_messages`(인덱스 없음, apps/api/CLAUDE.md)에서 LIMIT 100 이하로만 스캔하게 한다.
CHAT_MESSAGES_DEFAULT_LIMIT = 50
CHAT_MESSAGES_MAX_LIMIT = 100


async def _list_messages_page(
    db: AsyncSession,
    room_id: uuid.UUID,
    *,
    limit: int,
    before_created_at: datetime | None,
    before_id: uuid.UUID | None,
) -> AdminChatMessagesResponse:
    """techspec §4-5 커서 조건을 그대로 구현한다:

    ```sql
    WHERE chat_room_id = ?
      AND (created_at, id) < (:before_created_at, :before_id)
    ORDER BY created_at DESC, id DESC
    LIMIT :limit
    ```

    `created_at`만 비교하면 한 턴의 user·assistant 메시지가 같은 트랜잭션에 커밋돼
    타임스탬프가 같을 때 경계에서 메시지가 사라지거나 중복된다 — 반드시 `(created_at, id)`
    튜플로 비교한다(`content/router.py`의 `list_contents`와 같은 패턴).

    `limit`보다 하나 더 가져와 다음 페이지가 있는지(`has_more`)를 판정한다 —
    `list_contents`의 `CONTENT_LIST_PAGE_SIZE + 1` 패턴과 동일. 더 없으면 커서는 null.
    """
    query = select(ChatMessage).where(ChatMessage.chat_room_id == room_id)
    if before_created_at is not None and before_id is not None:
        query = query.where(
            tuple_(ChatMessage.created_at, ChatMessage.id) < (before_created_at, before_id)
        )

    rows = (
        await db.scalars(
            query.order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(limit + 1)
        )
    ).all()

    has_more = len(rows) > limit
    page = rows[:limit]

    return AdminChatMessagesResponse(
        items=[
            AdminChatMessageItem(id=m.id, role=m.role, content=m.content, created_at=m.created_at)
            for m in page
        ],
        before_created_at=page[-1].created_at if has_more else None,
        before_id=page[-1].id if has_more else None,
    )


@router.post("/admin/chat-rooms/{room_id}/view")
async def view_chat_room(
    room_id: uuid.UUID,
    body: AdminChatRoomViewRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminChatMessagesResponse:
    """techspec §4-5. **열람 1회 = 로그 1행**(T-6) — 로그는 이 엔드포인트에서만 쌓는다.
    더보기는 `GET .../messages`가 맡고 그쪽은 절대 로그를 쌓지 않는다."""
    if not body.reason_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="reason_text is required"
        )

    room = await db.get(ChatRoom, room_id)
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat room not found")

    response = await _list_messages_page(
        db, room_id, limit=CHAT_VIEW_MESSAGE_LIMIT, before_created_at=None, before_id=None
    )

    # target_chat_room_id는 "어느 방을 열람했는지", target_user_id(방 소유자)는
    # `admin/users.py`의 유저 상세 조치 이력(`target_user_id == user.id OR
    # target_content_id IN (...)`)에 이 로그가 걸리게 하는 용도다 — 둘 중 하나만
    # 채우면 유저 상세 화면에서 채팅 열람 기록이 보이지 않는다.
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="chat-view",
        target_user_id=room.user_id,
        target_chat_room_id=room_id,
        reason_category=body.reason_category.value,
        reason_text=body.reason_text,
    )
    await db.commit()

    return response


@router.get("/admin/chat-rooms/{room_id}/messages")
async def list_chat_room_messages(
    room_id: uuid.UUID,
    before_created_at: datetime | None = Query(None, alias="beforeCreatedAt"),
    before_id: uuid.UUID | None = Query(None, alias="beforeId"),
    limit: int = Query(CHAT_MESSAGES_DEFAULT_LIMIT, ge=1, le=CHAT_MESSAGES_MAX_LIMIT),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminChatMessagesResponse:
    """더보기 — **로그를 절대 쌓지 않는다**(T-6): "열람 1회 = 로그 1행"을 메서드로
    보장하는 장치라, 여기 `record_admin_action`을 추가하면 더보기 5번에 5행이 쌓인다."""
    room = await db.get(ChatRoom, room_id)
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat room not found")

    return await _list_messages_page(
        db, room_id, limit=limit, before_created_at=before_created_at, before_id=before_id
    )
