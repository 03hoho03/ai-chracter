import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import ColumnElement, and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import (
    AdminCloverLedgerItem,
    AdminCloverLedgerListResponse,
    AdminUserActionLogItem,
    AdminUserChatRoomItem,
    AdminUserCloverRequest,
    AdminUserDetailResponse,
    AdminUserListItem,
    AdminUserListResponse,
    AdminUserRateLimitExemptRequest,
    AdminUserReportItem,
    AdminUserSuspendRequest,
    AdminUserSuspendResponse,
    AdminUserUnsuspendRequest,
    AdminUserWarnRequest,
)
from api.core import clover
from api.db.models.auth import User
from api.db.models.clover import CloverLedger
from api.db.models.character import CharacterVersionDetail
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom
from api.db.models.content import Content, ContentType, ContentVisibility, ModerationStatus
from api.db.models.moderation import AdminActionLog, Notification, Report
from api.db.models.story import StoryVersionDetail
from api.db.session import get_db_session
from api.session.suspension import mark_user_suspended, unmark_user_suspended

router = APIRouter(tags=["admin"])

ADMIN_USER_PAGE_SIZE = 20

# 정지 시 restricted로 내려갈 작품의 판정 조건(그 유저의 공개 작품 전부 비공개 —
# PUBLIC과 LINK 둘 다 내리고 PRIVATE만 제외한다. LINK는 링크를 아는 사람이 열람할 수
# 있어 정지된 사용자의 콘텐츠가 계속 노출되기 때문이다). 한 번도 공개한 적 없는 PRIVATE
# 초안까지 내리면 정지 해제 후(자동 복구 없음) 관리자가 그 초안까지 하나씩 되돌려야
# 하는 부담이 생긴다. `suspend_user`의 UPDATE WHERE와 `_build_user_detail_response`의
# `restrictable_content_count` 계산이 반드시 같은 조건을 써야 하므로(어긋나면 정지 확인
# 다이얼로그의 예고와 실제 결과가 갈린다) 이 한 곳에만 정의해 두 곳에서 공유한다.
_RESTRICTABLE_CONTENT_CONDITION: ColumnElement[bool] = and_(
    Content.moderation_status == ModerationStatus.NORMAL,
    Content.visibility != ContentVisibility.PRIVATE,
)


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
    """탈퇴 유저(`deleted_at IS NOT NULL`)는
    제외한다. 작품 수·채팅방 수는 `GROUP BY` 서브쿼리를 `LEFT JOIN`해
    한 조회에 붙인다 — 행마다 COUNT를 부르지 않아, 이 엔드포인트는 COUNT 쿼리 1개 +
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
    # `restrictable_content_count`는 `_RESTRICTABLE_CONTENT_CONDITION`을 같은 조회에
    # boolean 컬럼으로 함께 실어 파생시킨다(새 쿼리를 늘리지 않기 위함) — `suspend_user()`의
    # UPDATE WHERE와 정확히 같은 조건 객체를 재사용하므로 두 곳이 어긋날 수 없다.
    user_contents = (
        await db.execute(
            select(Content.id, _RESTRICTABLE_CONTENT_CONDITION.label("restrictable")).where(
                Content.creator_user_id == user.id
            )
        )
    ).all()
    user_content_ids = [content_id for content_id, _ in user_contents]
    restrictable_content_count = sum(1 for _, restrictable in user_contents if restrictable)

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

    # 유일한 호출부 get_admin_user_detail이
    # deleted_at is not None인 유저를 404로 이미 배제한 뒤에만 이 함수를 부른다 — 탈퇴 유저는
    # 여기 도달하지 않으므로 nickname은 항상 채워져 있다.
    assert user.nickname is not None
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
        rate_limit_exempt=user.rate_limit_exempt,
        clover_balance=user.clover_balance,
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
    """알림만 보낸다 — 이용 제한 없음. `reason_category`가 필수인 이유는 통지
    문구가 사유를 인용하므로 제품 결정으로 필수라는 것이다 — 예전엔 아래에서 만드는
    `Notification.reason_category`가 NOT NULL이라는 DB 제약을 근거로 들었지만,
    이후 그 컬럼이 nullable로 바뀌어(공지·문의답변엔 인용할 사유가 없다) 그 근거가
    사라졌다.

    **이미 정지된 유저에게도 경고를 허용한다.** 경고(알림)와 정지(접근 차단)는 서로
    다른 축이라 정지 여부가 경고를 막을 이유가 없다 — 오히려 정지 중에도 별도 사유로
    주의를 주고 싶을 수 있다. 이를 금지하는 요구사항도 없다."""
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
    """아래 6단계를 정확한 순서로 수행한다.

    ```
    1. users.suspended_at = now()
    2. 그 유저의 PUBLIC/LINK contents.moderation_status = 'restricted'
       (visibility는 불변; PRIVATE는 제외)
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
    `_RESTRICTABLE_CONTENT_CONDITION`을 만족하는 작품만 내리므로 이미 내려간 작품은
    다시 세지 않아 재호출 시 `restricted_content_count`는 자연히 0에 수렴한다.
    """
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # 1.
    user.suspended_at = datetime.now(UTC)

    # 2. `_RESTRICTABLE_CONTENT_CONDITION`(NORMAL이면서 PRIVATE가 아닌 것)만 내린다.
    # 이미 restricted/deleted인 작품은 건드리지 않는다 — 안 그러면 이미 삭제 처리된
    # 작품이 restricted로 되살아나거나, 재호출마다
    # restricted_content_count가 실제로 안 내려간 작품까지 센다.
    # `.rowcount`(mypy strict에서 `Result[Any]`가 노출하지 않는 속성) 대신 `.returning()`
    # + `.scalars()`로 실제 변경된 행을 세어 이 코드베이스의 기존 조회 패턴을 유지한다.
    # 이 WHERE 조건은 `_build_user_detail_response`의 `restrictable_content_count`
    # 계산과 정확히 같은 `_RESTRICTABLE_CONTENT_CONDITION`을 쓴다(그쪽이 이 정지가
    # 내릴 작품 수를 미리 예고하는 값이라서다).
    restricted_content_ids = (
        await db.scalars(
            update(Content)
            .where(Content.creator_user_id == user_id, _RESTRICTABLE_CONTENT_CONDITION)
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
    """계정만 되살린다 — **작품은 restricted로 남는다**. 자동 복구하지 않으며,
    관리자가 작품 관리 화면(`/admin/contents`)에서 작품을 개별적으로 `lift-restriction`해야
    한다.

    `reason_category`는 받지 않는다 — 이 액션은 `Notification`을 만들지 않으므로 통지가
    없어 인용할 자리가 없다(경고/정지가 카테고리를 요구하는 것과 반대). 예전엔
    `Notification.reason_category`가 NOT NULL이라는 DB 제약을 근거로 들었지만, 이후
    그 컬럼이 nullable로 바뀌어 그 근거가 사라졌다. 대신 작품 직접 조치 `lift-restriction`과 같은
    규칙으로 `admin_comment`를 필수로 받는다 — 비어 있으면 422.

    **해제 알림은 보내지 않는다.** 요구사항이 경고·정지와 달리 해제에는 알림 발송을
    요구하지 않고, 정지와 달리 해제는 사용자가 다음 로그인에서 접근 복구 자체로
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


@router.post("/admin/users/{user_id}/rate-limit-exempt", status_code=status.HTTP_204_NO_CONTENT)
async def set_user_rate_limit_exempt(
    user_id: uuid.UUID,
    body: AdminUserRateLimitExemptRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """`users.rate_limit_exempt`를 바꾸는 **유일한** 경로다.
    Redis 미러도 세션 사본도 없어서(`core/rate_limit_gate.py`의 `is_rate_limit_exempt`)
    이 커밋 다음 요청부터 곧바로 적용된다 — 무효화할 캐시가 없다.

    면제 범위는 일일 상한과 이미지 토큰버킷뿐이고 분당 버스트·이미지 동시 큐 1칸은 예외
    계정에도 그대로 적용된다 — 그 범위는 어드민 확인 모달이 문장으로 알린다.

    **액션 타입이 켤 때와 끌 때 다르다**(`user-rate-limit-exempt-on` /
    `user-rate-limit-exempt-off`). `admin_action_logs.action_type`이 Text라 마이그레이션은
    없고, 두 타입을 나눠야 이력 표에서 "언제 켰고 언제 껐나"가 구분된다 — 한 타입에
    코멘트로만 담으면 그 구분이 사람이 읽는 자유 문자열로 내려간다.

    `reason_category`를 받지 않고 `admin_comment`를 필수로 받는 규칙은 `unsuspend_user`와
    같다(`Notification`을 만들지 않아 인용할 사유 자리가 없다).

    **같은 값을 다시 적용해도(True→True) 막지 않는다** — 대입은 멱등하고 `admin_action_logs`에는
    "누가 언제 눌렀다"가 한 행 더 남는다. 이미 정지된 유저의 재정지를 400으로 막지 않는
    `suspend_user`와 같은 관례다.

    순서: 상태 변경 → `record_admin_action` → `commit()`(Redis 단계가 없다).
    """
    if not (body.admin_comment or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="admin_comment is required"
        )

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.rate_limit_exempt = body.exempt
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="user-rate-limit-exempt-on" if body.exempt else "user-rate-limit-exempt-off",
        target_user_id=user_id,
        reason_text=body.admin_comment or "",
    )
    await db.commit()


@router.post("/admin/users/{user_id}/clover", status_code=status.HTTP_204_NO_CONTENT)
async def adjust_user_clover(
    user_id: uuid.UUID,
    body: AdminUserCloverRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """클로버를 지급(양수)하거나 회수(음수)하는 유일한 경로다.
    구조는 `set_user_rate_limit_exempt`의 4단계(검증 → 조회 → 변경 → 로그+커밋)를 그대로 따른다.

    🔴 **토글의 *"같은 값을 다시 적용해도 막지 않는다"*를 여기로 옮기면 안 된다.** 그 문장이
    성립했던 이유는 대입이 멱등이라서인데(True→True는 아무것도 안 바꾼다), **지급은 누적**이라
    두 번 도착하면 두 배가 들어온다. 그래서 `idempotency_key`가 필수이고
    `ux_clover_ledger_idempotency_key`가 그걸 강제한다.

    **호출자 세션을 쓴다** — 잔액·원장·`admin_action_logs`가 한 트랜잭션이라 셋 중 일부만
    남는 상태가 없다. `core/clover.py`의 자기-트랜잭션 래퍼(`*_in_new_transaction`)는 게이트
    전용이다: 채팅 4경로의 커밋 시점이 제각각이라 생긴 예외이고,
    어드민 라우트는 커밋 경계가 하나뿐이라 그 근거가 없다.

    ⇒ **"자원을 커밋한 뒤 되돌릴 수 있는 첫 지점까지"의 구간이 생기지 않는다.** 지급이
    커밋되는 시점과 감사 로그가 커밋되는 시점이 같은 `db.commit()`이고, 그 앞에서 실패하면
    둘 다 롤백된다. 클로버 도입 때 같은 구간이 네 번 나왔던 것은 전부 **자원 커밋과 기록 커밋이
    갈려 있던** 경로였다.

    `amount == 0`을 422로 막는 이유는 의미 없는 원장 행을 만들지 않기 위해서다 —
    `burn_all`이 잔액 0에서 아무것도 하지 않는 것과 같은 규칙이다.
    """
    if not (body.admin_comment or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="admin_comment is required"
        )
    if body.amount == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="amount must not be zero"
        )

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # 멱등키 중복은 `_apply`의 `flush()`에서 `IntegrityError`로 터진다. SAVEPOINT로 감싸는
    # 이유는 `auth/router.py`의 가입이 이메일 중복을 다루는 방식과 같다 — 요청 세션을 통째로
    # 롤백하면 유니크 위반 하나 때문에 이 요청이 이미 한 일(없지만, 앞으로 생길 수 있다)까지
    # 버리게 되고, 무엇보다 세션이 죽어 409를 만들 때 쓸 수도 없다.
    # 컨텍스트 매니저 형태를 쓰는 이유는 `auth/router.py:168-169`가 적은 것과 같다 —
    # CM이 SAVEPOINT까지만 되감아 세션을 정리하므로 `db.rollback()`도, 실패 경로마다
    # 손으로 부르는 `savepoint.rollback()`도 필요 없다. 아래 두 탈출구(422·409)가 전부
    # CM을 뚫고 나가며 되감기므로, 세 번째 탈출구가 생겨도 되감기를 빠뜨릴 수 없다.
    try:
        async with db.begin_nested():
            if body.amount > 0:
                await clover.grant(
                    db,
                    user_id=user_id,
                    amount=body.amount,
                    kind="admin_grant",
                    idempotency_key=body.idempotency_key,
                )
            else:
                balance_after = await clover.revoke(
                    db, user_id=user_id, amount=-body.amount, idempotency_key=body.idempotency_key
                )
                if balance_after is None:
                    # `revoke`의 `guard=True`가 막은 것이다 — 오지급 회수가 이미 쓴 만큼을 빚으로
                    # 남기지 않는다(잔액은 정수이고 음수 잔액은 없다).
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail="amount exceeds the current balance",
                    )
    except IntegrityError:
        # 409는 "재시도가 안전하다"는 신호다 — 같은 키로 다시 보내도 잔액이 더 늘지 않는다.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="idempotency_key already used"
        ) from None

    # 🔴 금액을 `admin_action_logs`에 담지 않는다 — 그 테이블에 숫자 컬럼이 0개라
    # `reason_text`에 문자열로 넣는 수밖에 없고, 그러면 "얼마를 줬나"의 집계가 영구히
    # 불가능해진다. **금액의 소재지는 원장**이고 이 로그는 "누가 언제 무엇을 했다"만 담는다.
    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="user-clover-grant" if body.amount > 0 else "user-clover-revoke",
        target_user_id=user_id,
        reason_text=body.admin_comment or "",
    )
    await db.commit()


@router.get("/admin/users/{user_id}/clover-ledger")
async def list_user_clover_ledger(
    user_id: uuid.UUID,
    page: int = Query(1, ge=1),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminCloverLedgerListResponse:
    """어드민용 원장 조회다 — 임의 유저를 본다(유저 본인용은 `GET /me/clover/ledger`).

    🔴 정렬 2차 키 `id`가 필수다. 오프셋 페이지네이션에서 동률 정렬이 불안정하면 같은 행이 두
    페이지에 나오거나 빠지는데, **원장은 한 트랜잭션에 여러 행이 들어갈 수 있어**(차감+환불이
    같은 요청에서 난다) `created_at`의 `server_default`(트랜잭션 시작 시각) 동률이
    `image_generation_requests`보다 흔하다. 선례는 `admin/image_generations.py`의
    `_list_owner_requests_page`.
    """
    total_count = (
        await db.scalar(
            select(func.count()).select_from(CloverLedger).where(CloverLedger.user_id == user_id)
        )
    ) or 0
    total_pages = -(-total_count // ADMIN_USER_PAGE_SIZE) if total_count else 0

    rows = (
        await db.scalars(
            select(CloverLedger)
            .where(CloverLedger.user_id == user_id)
            .order_by(CloverLedger.created_at.desc(), CloverLedger.id)
            .offset((page - 1) * ADMIN_USER_PAGE_SIZE)
            .limit(ADMIN_USER_PAGE_SIZE)
        )
    ).all()

    return AdminCloverLedgerListResponse(
        items=[
            AdminCloverLedgerItem(
                id=row.id,
                amount=row.amount,
                balance_after=row.balance_after,
                kind=row.kind,
                created_at=row.created_at,
            )
            for row in rows
        ],
        page=page,
        total_pages=total_pages,
        total_count=total_count,
    )
