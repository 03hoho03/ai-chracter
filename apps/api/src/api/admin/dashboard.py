import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import (
    AdminDashboardActivityResponse,
    AdminDashboardCountsResponse,
    AdminDashboardPopularItem,
    AdminDashboardRecentContent,
    AdminDashboardRecentReport,
    AdminDashboardRecentUser,
    AdminDashboardTrendPoint,
)
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail
from api.db.models.chat import ChatMessage, ChatMessageRole
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

    return AdminDashboardActivityResponse(
        recent_users=[
            AdminDashboardRecentUser(id=u.id, email=u.email, nickname=u.nickname, created_at=u.created_at)
            for u in recent_users
        ],
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
