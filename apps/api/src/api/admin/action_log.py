import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.moderation import AdminActionLog, AdminActionType, ModerationActionType

# backlog-l-goal-prompt.md BL-4: 콘텐츠 조치 → 감사 로그 액션 종류. 직접 조치
# (`admin/contents.py`)와 신고 조치(`moderation/router.py`)가 이 하나를 같이 쓴다.
# `REJECT`도 여기 둔다 — 그 멤버 자체가 "신고를 반려한다"는 뜻이라 어느 경로에서 읽어도
# 값이 `report-reject`로 같고, 직접 조치는 `reject`를 이미 400으로 막아 이 키를 조회하지 않는다.
# 값 타입을 적는 이유는 backlog-sweep Q-5(없으면 `dict[..., str]`로 추론돼 mypy에 걸린다).
ADMIN_ACTION_TYPE_BY_MODERATION_ACTION: dict[ModerationActionType, AdminActionType] = {
    ModerationActionType.RESTRICT: "content-restrict",
    ModerationActionType.DELETE: "content-delete",
    ModerationActionType.LIFT_RESTRICTION: "content-lift",
    ModerationActionType.REJECT: "report-reject",
}


async def record_admin_action(
    db: AsyncSession,
    *,
    admin_id: uuid.UUID,
    action_type: AdminActionType,
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
