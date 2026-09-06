import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import (
    AdminUserActionLogItem,
    AdminUserChatRoomItem,
    AdminUserDetailResponse,
    AdminUserListItem,
    AdminUserListResponse,
    AdminUserReportItem,
    AdminUserSuspendRequest,
    AdminUserSuspendResponse,
    AdminUserUnsuspendRequest,
    AdminUserWarnRequest,
)
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom
from api.db.models.content import Content, ContentType, ModerationStatus
from api.db.models.moderation import AdminActionLog, Notification, Report
from api.db.models.story import StoryVersionDetail
from api.db.session import get_db_session
from api.session.suspension import mark_user_suspended, unmark_user_suspended

router = APIRouter(tags=["admin"])

ADMIN_USER_PAGE_SIZE = 20


async def _content_names_by_id(db: AsyncSession, content_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    """N+1 회피 벌크 조회. 신고·조치로그·채팅방 세 섹션 전부 `content_id`만 들고 있어
    `admin/contents.py`/`admin/dashboard.py`의 헬퍼(이미 로드된 `Content`나 버전 id에서
    시작)와 입력 모양이 달라 새로 쓴다 — 파일 간 헬퍼 비공유 관례(apps/api/CLAUDE.md)."""
    ids = list(content_ids)
    if not ids:
        return {}

    contents = {
        content.id: content
        for content in (await db.scalars(select(Content).where(Content.id.in_(ids)))).all()
    }

    character_version_ids = [
        content.current_published_version_id
        for content in contents.values()
        if content.type == ContentType.CHARACTER and content.current_published_version_id is not None
    ]
    story_version_ids = [
        content.current_published_version_id
        for content in contents.values()
        if content.type == ContentType.STORY and content.current_published_version_id is not None
    ]

    names_by_version_id: dict[uuid.UUID, str] = {}
    if character_version_ids:
        for detail in (
            await db.scalars(
                select(CharacterVersionDetail).where(
                    CharacterVersionDetail.content_version_id.in_(character_version_ids)
                )
            )
        ).all():
            names_by_version_id[detail.content_version_id] = detail.name
    if story_version_ids:
        for story_detail in (
            await db.scalars(
                select(StoryVersionDetail).where(
                    StoryVersionDetail.content_version_id.in_(story_version_ids)
                )
            )
        ).all():
            names_by_version_id[story_detail.content_version_id] = story_detail.name

    return {
        content_id: (
            names_by_version_id.get(content.current_published_version_id, "")
            if content.current_published_version_id
            else ""
        )
        for content_id, content in contents.items()
    }


@router.get("/admin/users")
async def list_admin_users(
    page: int = Query(1, ge=1),
    q: str | None = Query(None),
    suspended: bool | None = Query(None),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminUserListResponse:
    """techspec.md §4-3, goal-prompt.md 3단계. 탈퇴 유저(`deleted_at IS NOT NULL`)는
    제외한다(goal-prompt §3-5). 작품 수·채팅방 수는 `GROUP BY` 서브쿼리를 `LEFT JOIN`해
    한 조회에 붙인다(T-8) — 행마다 COUNT를 부르지 않아, 이 엔드포인트는 COUNT 쿼리 1개 +
    본 조회 1개, 총 2개로 끝난다."""
    filters: list[ColumnElement[bool]] = [User.deleted_at.is_(None)]
    if q:
        filters.append(or_(User.email.ilike(f"%{q}%"), User.nickname.ilike(f"%{q}%")))
    if suspended is not None:
        filters.append(User.suspended_at.is_not(None) if suspended else User.suspended_at.is_(None))

    total_count = (await db.scalar(select(func.count()).select_from(User).where(*filters))) or 0
    total_pages = -(-total_count // ADMIN_USER_PAGE_SIZE) if total_count else 0

    content_counts = (
        select(Content.creator_user_id.label("user_id"), func.count().label("content_count"))
        .group_by(Content.creator_user_id)
        .subquery()
    )
    chat_room_counts = (
        select(ChatRoom.user_id.label("user_id"), func.count().label("chat_room_count"))
        .group_by(ChatRoom.user_id)
        .subquery()
    )

    # 동점(같은 created_at) 시 순서가 흔들리면 offset 페이지네이션에서 행이 중복되거나
    # 누락된다(`admin/contents.py`의 정렬과 같은 이유) — `id`까지 더해 결정적으로 만든다.
    rows = (
        await db.execute(
            select(
                User,
                func.coalesce(content_counts.c.content_count, 0),
                func.coalesce(chat_room_counts.c.chat_room_count, 0),
            )
            .outerjoin(content_counts, content_counts.c.user_id == User.id)
            .outerjoin(chat_room_counts, chat_room_counts.c.user_id == User.id)
            .where(*filters)
            .order_by(User.created_at.desc(), User.id)
            .offset((page - 1) * ADMIN_USER_PAGE_SIZE)
            .limit(ADMIN_USER_PAGE_SIZE)
        )
    ).all()

    items = [
        AdminUserListItem(
            id=user.id,
            email=user.email,
            nickname=user.nickname,
            created_at=user.created_at,
            suspended_at=user.suspended_at,
            content_count=content_count,
            chat_room_count=chat_room_count,
        )
        for user, content_count, chat_room_count in rows
    ]

    return AdminUserListResponse(
        items=items, page=page, total_pages=total_pages, total_count=total_count
    )


async def _build_user_detail_response(db: AsyncSession, user: User) -> AdminUserDetailResponse:
    """`GET /admin/users/{id}`의 조립 로직. 이름 채우기는 전부 벌크 조회이고, 방마다
    쿼리를 돌리지 않는다 — 채팅방 메시지 수·마지막 시각은 GROUP BY 벌크로 한 번에 붙인다."""
    # `moderation_status`도 같은 조회에 함께 실어 `restrictable_content_count`를 파생시킨다
    # (새 쿼리를 늘리지 않기 위함) — 이 필드의 정의(NORMAL인 것만 셈)는 `suspend_user()`의
    # UPDATE WHERE(`creator_user_id == user.id AND moderation_status == NORMAL`)와 정확히
    # 같아야 한다. 두 곳이 어긋나면 정지 확인 다이얼로그의 예고와 실제 결과가 다시 갈린다.
    user_contents = (
        await db.execute(
            select(Content.id, Content.moderation_status).where(Content.creator_user_id == user.id)
        )
    ).all()
    user_content_ids = [content_id for content_id, _ in user_contents]
    restrictable_content_count = sum(
        1 for _, moderation_status in user_contents if moderation_status == ModerationStatus.NORMAL
    )

    chat_room_count = (
        await db.scalar(select(func.count()).select_from(ChatRoom).where(ChatRoom.user_id == user.id))
    ) or 0

    message_count, last_active_at = (
        await db.execute(
            select(func.count(ChatMessage.id), func.max(ChatMessage.created_at))
            .select_from(ChatMessage)
            .join(ChatRoom, ChatRoom.id == ChatMessage.chat_room_id)
            .where(ChatRoom.user_id == user.id, ChatMessage.role == ChatMessageRole.USER)
        )
    ).one()

    reports: Sequence[Report] = []
    if user_content_ids:
        reports = (
            await db.scalars(
                select(Report)
                .where(Report.content_id.in_(user_content_ids))
                .order_by(Report.created_at.desc(), Report.id)
                .limit(20)
            )
        ).all()

    # `target_content_id.in_([])`는 SQLAlchemy가 "항상 거짓"으로 렌더링하며 빈 시퀀스
    # 경고를 낸다 — 조건 자체를 조건부로 추가해 피한다.
    action_log_conditions = [AdminActionLog.target_user_id == user.id]
    if user_content_ids:
        action_log_conditions.append(AdminActionLog.target_content_id.in_(user_content_ids))
    action_logs = (
        await db.scalars(
            select(AdminActionLog)
            .where(or_(*action_log_conditions))
            .order_by(AdminActionLog.created_at.desc(), AdminActionLog.id)
            .limit(20)
        )
    ).all()

    chat_rooms = (
        await db.scalars(
            select(ChatRoom)
            .where(ChatRoom.user_id == user.id)
            .order_by(ChatRoom.created_at.desc(), ChatRoom.id)
            .limit(20)
        )
    ).all()

    room_stats_by_room_id: dict[uuid.UUID, tuple[int, datetime | None]] = {}
    if chat_rooms:
        room_ids = [room.id for room in chat_rooms]
        room_stat_rows = await db.execute(
            select(ChatMessage.chat_room_id, func.count(), func.max(ChatMessage.created_at))
            .where(ChatMessage.chat_room_id.in_(room_ids))
            .group_by(ChatMessage.chat_room_id)
        )
        for chat_room_id, room_message_count, room_last_message_at in room_stat_rows:
            room_stats_by_room_id[chat_room_id] = (room_message_count, room_last_message_at)

    all_content_ids: set[uuid.UUID] = {
        *(report.content_id for report in reports),
        *(log.target_content_id for log in action_logs if log.target_content_id is not None),
        *(room.content_id for room in chat_rooms),
    }
    content_names_by_id = await _content_names_by_id(db, all_content_ids)

    return AdminUserDetailResponse(
        id=user.id,
        email=user.email,
        nickname=user.nickname,
        bio=user.bio,
        created_at=user.created_at,
        suspended_at=user.suspended_at,
        email_verified_at=user.email_verified_at,
        signup_method="google" if user.google_sub is not None else "email",
        content_count=len(user_content_ids),
        restrictable_content_count=restrictable_content_count,
        chat_room_count=chat_room_count,
        message_count=message_count,
        last_active_at=last_active_at,
        reports=[
            AdminUserReportItem(
                id=report.id,
                reason_category=report.reason_category,
                status=report.status,
                content_id=report.content_id,
                content_name=content_names_by_id.get(report.content_id, ""),
                created_at=report.created_at,
            )
            for report in reports
        ],
        action_logs=[
            AdminUserActionLogItem(
                id=log.id,
                action_type=log.action_type,
                target_content_id=log.target_content_id,
                content_name=(
                    content_names_by_id.get(log.target_content_id, "")
                    if log.target_content_id is not None
                    else None
                ),
                reason_category=log.reason_category,
                reason_text=log.reason_text,
                created_at=log.created_at,
            )
            for log in action_logs
        ],
        chat_rooms=[
            AdminUserChatRoomItem(
                id=room.id,
                content_id=room.content_id,
                content_name=content_names_by_id.get(room.content_id, ""),
                name=room.name,
                turn_count=room.turn_count,
                message_count=room_stats_by_room_id.get(room.id, (0, None))[0],
                last_message_at=room_stats_by_room_id.get(room.id, (0, None))[1],
                created_at=room.created_at,
            )
            for room in chat_rooms
        ],
    )


@router.get("/admin/users/{user_id}")
async def get_admin_user_detail(
    user_id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminUserDetailResponse:
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return await _build_user_detail_response(db, user)


@router.post("/admin/users/{user_id}/warn", status_code=status.HTTP_204_NO_CONTENT)
async def warn_user(
    user_id: uuid.UUID,
    body: AdminUserWarnRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """알림만 보낸다 — 이용 제한 없음(D-5). `reason_category`가 필수인 이유는 아래에서
    만드는 `Notification.reason_category`가 NOT NULL이기 때문(T-2).

    **이미 정지된 유저에게도 경고를 허용한다.** 경고(알림)와 정지(접근 차단)는 서로
    다른 축이라 정지 여부가 경고를 막을 이유가 없다 — 오히려 정지 중에도 별도 사유로
    주의를 주고 싶을 수 있다. goal-prompt/techspec 어디에도 이를 금지하는 근거가 없다."""
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    db.add(
        Notification(
            user_id=user_id,
            type="user-warned",
            content_id=None,
            action_id=None,
            reason_category=body.reason_category.value,
            admin_comment=body.admin_comment or "",
        )
    )
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="user-warn",
        target_user_id=user_id,
        reason_category=body.reason_category.value,
        reason_text=body.admin_comment or "",
    )
    await db.commit()


@router.post("/admin/users/{user_id}/suspend")
async def suspend_user(
    user_id: uuid.UUID,
    body: AdminUserSuspendRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminUserSuspendResponse:
    """techspec.md §2-2의 6단계를 정확한 순서로 수행한다.

    ```
    1. users.suspended_at = now()
    2. 그 유저의 contents.moderation_status = 'restricted' (visibility는 불변, T-1)
    3. Notification(type='user-suspended', content_id=None, action_id=None)
    4. record_admin_action(action_type='user-suspend')
    5. db.commit()                  ← 여기까지 원자적
    6. mark_user_suspended(user_id) ← Redis. 실패하면 500
    ```

    **순서가 중요하다 — DB가 진실이므로 먼저 확정한다.** 6이 실패하면(여기서 별도
    try/except 없이 그대로 예외가 전파돼 500이 된다) "DB엔 정지인데 마커가 없는" 상태로
    끝나고, 관리자가 다시 이 엔드포인트를 누르면 1~5는 멱등하게 재실행되며 6만 다시
    시도된다.

    **이미 정지된 유저를 다시 정지시켜도 400을 던지지 않고 그대로 통과시킨다.** 위
    재시도 시나리오(6 실패 후 재호출)가 정확히 "이미 `suspended_at`이 있는 유저에 대한
    두 번째 suspend 호출"이라, 여기서 막으면 그 복구 경로 자체가 사라진다. 매 호출은
    멱등하게 동작한다 — `suspended_at`은 호출 시각으로 다시 세팅되고, 아래 2단계가
    `moderation_status == NORMAL`인 작품만 내리므로 이미 내려간 작품은 다시 세지 않아
    재호출 시 `restricted_content_count`는 자연히 0에 수렴한다.
    """
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # 1.
    user.suspended_at = datetime.now(UTC)

    # 2. 이미 restricted거나 deleted인 작품은 건드리지 않는다 — NORMAL인 것만 내린다.
    # 안 그러면 이미 삭제 처리된 작품이 restricted로 되살아나거나(T-1과 같은 종류의
    # 사고), 재호출마다 restricted_content_count가 실제로 안 내려간 작품까지 센다.
    # `.rowcount`(mypy strict에서 `Result[Any]`가 노출하지 않는 속성) 대신 `.returning()`
    # + `.scalars()`로 실제 변경된 행을 세어 이 코드베이스의 기존 조회 패턴을 유지한다.
    # 이 WHERE 조건은 `_build_user_detail_response`의 `restrictable_content_count`
    # 계산과 정확히 같아야 한다(그쪽이 이 정지가 내릴 작품 수를 미리 예고하는 값이라서다).
    restricted_content_ids = (
        await db.scalars(
            update(Content)
            .where(Content.creator_user_id == user_id, Content.moderation_status == ModerationStatus.NORMAL)
            .values(moderation_status=ModerationStatus.RESTRICTED)
            .returning(Content.id)
        )
    ).all()
    restricted_content_count = len(restricted_content_ids)

    # 3.
    db.add(
        Notification(
            user_id=user_id,
            type="user-suspended",
            content_id=None,
            action_id=None,
            reason_category=body.reason_category.value,
            admin_comment=body.admin_comment or "",
        )
    )

    # 4.
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="user-suspend",
        target_user_id=user_id,
        reason_category=body.reason_category.value,
        reason_text=body.admin_comment or "",
    )

    # 5.
    await db.commit()

    # 6.
    await mark_user_suspended(user_id)

    return AdminUserSuspendResponse(restricted_content_count=restricted_content_count)


@router.post("/admin/users/{user_id}/unsuspend", status_code=status.HTTP_204_NO_CONTENT)
async def unsuspend_user(
    user_id: uuid.UUID,
    body: AdminUserUnsuspendRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """계정만 되살린다 — **작품은 restricted로 남는다(D-7)**. 자동 복구하지 않으며,
    관리자가 2단계 화면(`/admin/contents`)에서 작품을 개별적으로 `lift-restriction`해야
    한다.

    `reason_category`는 받지 않는다 — 이 액션은 `Notification`을 만들지 않으므로
    `Notification.reason_category` NOT NULL을 근거로 필수화할 이유가 없다(경고/정지가
    카테고리를 요구하는 것과 반대). 대신 2단계 `lift-restriction`과 같은 규칙으로
    `admin_comment`를 필수로 받는다 — 비어 있으면 422.

    **해제 알림은 보내지 않는다.** goal-prompt가 경고·정지와 달리 해제에는 알림 발송을
    명시하지 않았고, 정지와 달리 해제는 사용자가 다음 로그인에서 접근 복구 자체로
    상태 변화를 알 수 있어(정지는 접근이 막히는 순간 이유를 알 방법이 알림뿐이라 필수인
    것과 대칭) 별도 통지 없이도 정보 비대칭이 생기지 않는다.

    순서: `suspended_at = None` → `record_admin_action` → `commit()` → Redis `DEL`.
    """
    if not (body.admin_comment or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="admin_comment is required"
        )

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.suspended_at = None
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="user-unsuspend",
        target_user_id=user_id,
        reason_text=body.admin_comment or "",
    )
    await db.commit()

    await unmark_user_suspended(user_id)
