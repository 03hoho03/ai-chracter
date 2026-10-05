import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import (
    AdminDashboardActivityResponse,
    AdminDashboardCohort,
    AdminDashboardCohortWeekPoint,
    AdminDashboardCountsResponse,
    AdminDashboardGrowthResponse,
    AdminDashboardPopularItem,
    AdminDashboardRecentContent,
    AdminDashboardRecentReport,
    AdminDashboardRecentUser,
    AdminDashboardTrendPoint,
)
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom
from api.db.models.content import Content, ContentType
from api.db.models.moderation import Report, ReportStatus
from api.db.models.story import StoryVersionDetail
from api.db.session import get_db_session

router = APIRouter(tags=["admin"])


async def _content_names_by_version_id(
    db: AsyncSession, contents: Iterable[Content]
) -> dict[uuid.UUID, str]:
    """N+1 회피 벌크 조회. `moderation/router.py`의 `_admin_report_list_items`와 같은
    패턴이지만, 파일 간 헬퍼 비공유 관례(apps/api/CLAUDE.md)에 따라 이 파일에 복제한다."""
    content_list = list(contents)
    character_version_ids = [
        content.current_published_version_id
        for content in content_list
        if content.type == ContentType.CHARACTER and content.current_published_version_id is not None
    ]
    story_version_ids = [
        content.current_published_version_id
        for content in content_list
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
    return names_by_version_id


@router.get("/admin/dashboard/counts")
async def get_dashboard_counts(
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminDashboardCountsResponse:
    """`total_contents`는 `moderation_status`로 거르지 않는다 — 이용제한·삭제 조치된
    작품도 존재하는 작품이므로 전체 행 수를 그대로 센다."""
    today_start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)

    total_users = (
        await db.scalar(select(func.count()).select_from(User).where(User.deleted_at.is_(None)))
    ) or 0
    total_contents = (await db.scalar(select(func.count()).select_from(Content))) or 0
    today_messages = (
        await db.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(
                ChatMessage.role == ChatMessageRole.USER,
                ChatMessage.created_at >= today_start,
            )
        )
    ) or 0
    pending_reports = (
        await db.scalar(
            select(func.count()).select_from(Report).where(Report.status == ReportStatus.PENDING)
        )
    ) or 0

    return AdminDashboardCountsResponse(
        total_users=total_users,
        total_contents=total_contents,
        today_messages=today_messages,
        pending_reports=pending_reports,
    )


@router.get("/admin/dashboard/trend")
async def get_dashboard_trend(
    days: int = Query(30, ge=1, le=365),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[AdminDashboardTrendPoint]:
    """일별 신규가입·신규작품·메시지 3축을 각각 group-by 쿼리로 뽑아 빈 날은 0으로
    채운다(`get_usage_metrics`의 `while day <= to_date` 패턴). `signups`는 `deleted_at`
    필터를 걸지 않는다 — 그날 가입한 사실은 나중에 탈퇴해도 그대로 사실이다."""
    to_date = datetime.now(UTC).date()
    from_date = to_date - timedelta(days=days - 1)
    range_start = datetime.combine(from_date, time.min, tzinfo=UTC)
    range_end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=UTC)

    signup_rows = (
        await db.execute(
            select(func.date(User.created_at).label("day"), func.count().label("signup_count"))
            .where(User.created_at >= range_start, User.created_at < range_end)
            .group_by(func.date(User.created_at))
        )
    ).all()
    signups_by_day = {row.day: row.signup_count for row in signup_rows}

    content_rows = (
        await db.execute(
            select(func.date(Content.created_at).label("day"), func.count().label("content_count"))
            .where(Content.created_at >= range_start, Content.created_at < range_end)
            .group_by(func.date(Content.created_at))
        )
    ).all()
    contents_by_day = {row.day: row.content_count for row in content_rows}

    message_rows = (
        await db.execute(
            select(func.date(ChatMessage.created_at).label("day"), func.count().label("message_count"))
            .where(
                ChatMessage.role == ChatMessageRole.USER,
                ChatMessage.created_at >= range_start,
                ChatMessage.created_at < range_end,
            )
            .group_by(func.date(ChatMessage.created_at))
        )
    ).all()
    messages_by_day = {row.day: row.message_count for row in message_rows}

    trend: list[AdminDashboardTrendPoint] = []
    day = from_date
    while day <= to_date:
        trend.append(
            AdminDashboardTrendPoint(
                date=day,
                signups=signups_by_day.get(day, 0),
                contents=contents_by_day.get(day, 0),
                messages=messages_by_day.get(day, 0),
            )
        )
        day += timedelta(days=1)

    return trend


@router.get("/admin/dashboard/popular")
async def get_dashboard_popular(
    limit: int = Query(10, ge=1, le=50),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[AdminDashboardPopularItem]:
    """조인 없이 `chat_count` 컬럼 그대로 내림차순 정렬한다. 썸네일은 넣지 않는다 —
    presigned URL 서명이 행마다 붙어 비용만 늘어난다. `chat_count`만으로는 신규 등록작
    (전부 0)이 11개 이상이면 매 호출마다 Top 10 구성·순서가 바뀌므로, `created_at DESC`
    다음 `id`까지 더해 완전히 결정적인 정렬을 만든다."""
    contents = (
        await db.scalars(
            select(Content)
            .order_by(Content.chat_count.desc(), Content.created_at.desc(), Content.id)
            .limit(limit)
        )
    ).all()
    names_by_version_id = await _content_names_by_version_id(db, contents)

    return [
        AdminDashboardPopularItem(
            id=content.id,
            type=content.type,
            name=(
                names_by_version_id.get(content.current_published_version_id, "")
                if content.current_published_version_id
                else ""
            ),
            chat_count=content.chat_count,
            view_count=content.view_count,
            like_count=content.like_count,
        )
        for content in contents
    ]


@router.get("/admin/dashboard/activity")
async def get_dashboard_activity(
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminDashboardActivityResponse:
    recent_users = (
        await db.scalars(
            select(User).where(User.deleted_at.is_(None)).order_by(User.created_at.desc()).limit(5)
        )
    ).all()

    recent_contents = (
        await db.scalars(select(Content).order_by(Content.created_at.desc()).limit(5))
    ).all()
    content_names_by_version_id = await _content_names_by_version_id(db, recent_contents)

    recent_reports = (
        await db.scalars(select(Report).order_by(Report.created_at.desc()).limit(5))
    ).all()
    report_contents = {
        content.id: content
        for content in (
            await db.scalars(
                select(Content).where(Content.id.in_(report.content_id for report in recent_reports))
            )
        ).all()
    }
    report_names_by_version_id = await _content_names_by_version_id(db, report_contents.values())

    recent_report_items: list[AdminDashboardRecentReport] = []
    for report in recent_reports:
        version_id = report_contents[report.content_id].current_published_version_id
        recent_report_items.append(
            AdminDashboardRecentReport(
                id=report.id,
                reason_category=report.reason_category,
                content_id=report.content_id,
                content_name=report_names_by_version_id.get(version_id, "") if version_id else "",
                status=report.status,
                created_at=report.created_at,
            )
        )

    recent_user_items: list[AdminDashboardRecentUser] = []
    for u in recent_users:
        # 위 쿼리(:210)가 deleted_at.is_(None)으로 이미 필터링했다 — nickname은 탈퇴(S5 파기)
        # 시에만 None이 된다.
        assert u.nickname is not None
        recent_user_items.append(
            AdminDashboardRecentUser(id=u.id, email=u.email, nickname=u.nickname, created_at=u.created_at)
        )

    return AdminDashboardActivityResponse(
        recent_users=recent_user_items,
        recent_contents=[
            AdminDashboardRecentContent(
                id=content.id,
                type=content.type,
                name=(
                    content_names_by_version_id.get(content.current_published_version_id, "")
                    if content.current_published_version_id
                    else ""
                ),
                created_at=content.created_at,
            )
            for content in recent_contents
        ],
        recent_reports=recent_report_items,
    )


_MAX_COHORT_WEEK_OFFSET = 7  # W0~W7(8주) — 사용자 확정 지침의 예시를 그대로 따른다.
# 그 이상은 프로덕션 가입자(11명) 표본이 코호트별로 더 잘게 쪼개져 유지율이 무의미해진다.


def _week_start(dt: datetime) -> date:
    """그 날짜가 속한 주(월요일 시작)의 첫날. 코호트 단위(주)를 캘린더 주 경계로 정의한다."""
    d = dt.date()
    return d - timedelta(days=d.weekday())


async def _active_user_weeks(db: AsyncSession, *, beta: bool) -> list[tuple[uuid.UUID, date]]:
    """사용자 메시지를 보낸 (사용자, 그 주 월요일) 쌍. 메시지 행을 전부 받아 오면 긴 방 하나가 턴
    수만큼 행을 늘리므로 DB 에서 주 단위로 접어 중복 없이 받는다.

    주 경계는 `_week_start` 와 같은 UTC 날짜 기준이어야 한다. `date_trunc` 는 `timestamptz` 를
    연결의 세션 타임존으로 자르므로 먼저 UTC 벽시계 시각으로 바꾼다(`timezone('UTC', …)` =
    `AT TIME ZONE 'UTC'`). Postgres 의 `'week'` 도 월요일 시작이다.

    `beta=True` 면 각 사용자의 베타 지정 시각 이후 메시지만 센다. 접기 전에 걸러야 지정한 주 안의
    지정 전 활동이 그 주를 활동 주로 만들지 않는다."""
    week_start = cast(func.date_trunc("week", func.timezone("UTC", ChatMessage.created_at)), Date)
    query = (
        select(ChatRoom.user_id, week_start.label("week_start"))
        .select_from(ChatMessage)
        .join(ChatRoom, ChatMessage.chat_room_id == ChatRoom.id)
        .where(ChatMessage.role == ChatMessageRole.USER)
        .distinct()
    )
    if beta:
        query = query.join(User, User.id == ChatRoom.user_id).where(ChatMessage.created_at >= User.beta_joined_at)
    return [(user_id, week) for user_id, week in (await db.execute(query)).all()]


async def _cohort_retention(db: AsyncSession, *, beta: bool = False) -> list[AdminDashboardCohort]:
    """가입 주차 코호트별 유지율. **근사다** — 로그인 이벤트가 DB에 없어(`last_login`류
    필드 0건) '재방문'을 '그 주에 `ChatMessage.role == USER` 메시지를 보냈는가'로
    대체한다. 정확한 재방문율이 아니다. 아직 해당 주차에 도달하지 못한 코호트는 도달한
    주차까지만 채운다 — `trend`처럼 미래를 0으로 채우면 '유지 안 함'과 '아직 관측
    불가'가 구분되지 않는다.

    `beta=True`면 베타 참가자로 지정된 사용자만 세고, 코호트를 가입 주차가 아니라 **베타
    지정 주차**로 묶는다. 베타 전에 가입한 사용자를 지정해도 0주차가 지정한 주가 되게 하려는
    것이다. 주차는 월요일 단위라 지정한 주 안에서도 지정 시각보다 앞선 메시지가 0주차로
    떨어지므로, 각 사용자의 지정 시각 이전 메시지는 아예 세지 않는다 — 0주차는 지정 후 그
    주 안의 활동이어야 한다. 전체 모드에선 가입 전 메시지가 있을 수 없어 이 거름이 필요 없다."""
    cohort_at = User.beta_joined_at if beta else User.created_at
    user_query = select(User.id, cohort_at.label("cohort_at")).where(User.deleted_at.is_(None))
    if beta:
        user_query = user_query.where(User.beta_joined_at.is_not(None))
    user_rows = (await db.execute(user_query)).all()
    if not user_rows:
        return []

    cohort_start_by_user = {row.id: _week_start(row.cohort_at) for row in user_rows}
    cohort_users: dict[date, set[uuid.UUID]] = {}
    for user_id, signup_week in cohort_start_by_user.items():
        cohort_users.setdefault(signup_week, set()).add(user_id)

    retained_by_cohort_offset: dict[tuple[date, int], set[uuid.UUID]] = {}
    for user_id, active_week_start in await _active_user_weeks(db, beta=beta):
        cohort_start = cohort_start_by_user.get(user_id)
        if cohort_start is None:
            continue  # 탈퇴 유저 — 코호트 분모에서 이미 빠졌다.
        offset = (active_week_start - cohort_start).days // 7
        if 0 <= offset <= _MAX_COHORT_WEEK_OFFSET:
            retained_by_cohort_offset.setdefault((cohort_start, offset), set()).add(user_id)

    now_week_start = _week_start(datetime.now(UTC))
    cohorts: list[AdminDashboardCohort] = []
    for cohort_start in sorted(cohort_users):
        cohort_size = len(cohort_users[cohort_start])
        max_offset = min(_MAX_COHORT_WEEK_OFFSET, (now_week_start - cohort_start).days // 7)
        weeks = [
            AdminDashboardCohortWeekPoint(
                week_offset=offset,
                retained_users=len(retained_by_cohort_offset.get((cohort_start, offset), set())),
                retention_rate=(
                    len(retained_by_cohort_offset.get((cohort_start, offset), set())) / cohort_size
                ),
            )
            for offset in range(max_offset + 1)
        ]
        cohorts.append(
            AdminDashboardCohort(cohort_week_start=cohort_start, cohort_size=cohort_size, weeks=weeks)
        )
    return cohorts


@router.get("/admin/dashboard/growth")
async def get_dashboard_growth(
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminDashboardGrowthResponse:
    """가입자 성장 지표 — 새 수집 없이 기존 DB만 재구성한다(처리방침 개정 불필요, 외부
    미전송). `activation_rate`(가입자→첫 대화 도달률)의 분자는 방 생성이 아니라 실제
    `ChatMessage.role == USER` 메시지를 보낸 유저 distinct count다(`ChatRoom` 경유 조인
    필수 — 방만 만들고 메시지를 안 보낸 유저는 도달로 치지 않는다). `publish_rate`(제작자→
    발행 완료율)의 분자는 기존 발행 완료 관용구(`content/router.py`의
    `current_published_version_id.is_not(None)`)를 그대로 쓴다. `cohort_retention`은
    `_cohort_retention`의 docstring대로 **근사**다."""
    total_users = (
        await db.scalar(select(func.count()).select_from(User).where(User.deleted_at.is_(None)))
    ) or 0
    total_signups = (await db.scalar(select(func.count()).select_from(User))) or 0
    withdrawn_users = (
        await db.scalar(select(func.count()).select_from(User).where(User.deleted_at.is_not(None)))
    ) or 0

    activated_users = (
        await db.scalar(
            select(func.count(func.distinct(ChatRoom.user_id)))
            .select_from(ChatMessage)
            .join(ChatRoom, ChatMessage.chat_room_id == ChatRoom.id)
            .join(User, ChatRoom.user_id == User.id)
            .where(ChatMessage.role == ChatMessageRole.USER, User.deleted_at.is_(None))
        )
    ) or 0

    creators_with_published_content = (
        await db.scalar(
            select(func.count(func.distinct(Content.creator_user_id)))
            .select_from(Content)
            .join(User, Content.creator_user_id == User.id)
            .where(Content.current_published_version_id.is_not(None), User.deleted_at.is_(None))
        )
    ) or 0

    users_with_content = (
        await db.scalar(
            select(func.count(func.distinct(Content.creator_user_id)))
            .select_from(Content)
            .join(User, Content.creator_user_id == User.id)
            .where(User.deleted_at.is_(None))
        )
    ) or 0

    return AdminDashboardGrowthResponse(
        total_users=total_users,
        activated_users=activated_users,
        activation_rate=activated_users / total_users if total_users else 0.0,
        creators_with_published_content=creators_with_published_content,
        publish_rate=creators_with_published_content / total_users if total_users else 0.0,
        total_signups=total_signups,
        withdrawn_users=withdrawn_users,
        withdrawn_rate=withdrawn_users / total_signups if total_signups else 0.0,
        users_with_content=users_with_content,
        creator_rate=users_with_content / total_users if total_users else 0.0,
        cohort_retention=await _cohort_retention(db),
    )


@router.get("/admin/dashboard/cohort-retention")
async def get_dashboard_cohort_retention(
    beta: bool = Query(False),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> list[AdminDashboardCohort]:
    """코호트 유지율만 따로 준다. `beta=false`(기본)는 `/growth`의 `cohort_retention`과 같은
    값이고, `beta=true`는 베타 참가자만 지정 주차 기준으로 묶는다(`_cohort_retention` 참고).
    `/growth`에 파라미터를 더하지 않은 이유는 한 응답 안에서 이 필드만 베타로 걸러지고 나머지
    지표는 전체 기준으로 남아 섞여 읽히기 때문이다."""
    return await _cohort_retention(db, beta=beta)
