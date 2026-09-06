import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.moderation import AdminActionLog


async def record_admin_action(
    db: AsyncSession,
    *,
    admin_id: uuid.UUID,
    action_type: str,
    target_user_id: uuid.UUID | None = None,
    target_content_id: uuid.UUID | None = None,
    target_chat_room_id: uuid.UUID | None = None,
    reason_category: str | None = None,
    reason_text: str = "",
) -> None:
    """techspec.md §3(TS-7). 콘텐츠 조치·유저 제재·채팅 열람을 한 형식으로 담는 감사
    로그에 행을 하나 추가한다.

    키워드 전용(`*`)인 이유: `target_user_id`/`target_content_id`/`target_chat_room_id`
    셋 다 타입이 `uuid.UUID | None`으로 동일해서, 위치 인자로 받으면 호출부가 순서를
    바꿔 넘겨도 타입 체커가 잡아내지 못한다.

    `db.add()`만 하고 커밋하지 않는다 — 호출자의 트랜잭션에 얹혀서 조치와 로그가 같이
    커밋되거나 같이 롤백된다.
    """
    db.add(
        AdminActionLog(
            admin_id=admin_id,
            action_type=action_type,
            target_user_id=target_user_id,
            target_content_id=target_content_id,
            target_chat_room_id=target_chat_room_id,
            reason_category=reason_category,
            reason_text=reason_text,
        )
    )
