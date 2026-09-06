import uuid
from datetime import date, datetime

from pydantic import EmailStr

from api.core.schema import CamelModel
from api.db.models.content import ContentType
from api.db.models.moderation import ReportReasonCategory, ReportStatus


class AdminLoginRequest(CamelModel):
    email: EmailStr
    password: str


class AdminMeResponse(CamelModel):
    id: uuid.UUID
    email: str


class AdminDashboardCountsResponse(CamelModel):
    total_users: int
    total_contents: int
    today_messages: int
    pending_reports: int


class AdminDashboardTrendPoint(CamelModel):
    date: date
    signups: int
    contents: int
    messages: int


class AdminDashboardPopularItem(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    chat_count: int
    view_count: int
    like_count: int


class AdminDashboardRecentUser(CamelModel):
    id: uuid.UUID
    email: str
    nickname: str
    created_at: datetime


class AdminDashboardRecentContent(CamelModel):
    id: uuid.UUID
    type: ContentType
    name: str
    created_at: datetime


class AdminDashboardRecentReport(CamelModel):
    id: uuid.UUID
    reason_category: ReportReasonCategory
    content_id: uuid.UUID
    content_name: str
    status: ReportStatus
    created_at: datetime


class AdminDashboardActivityResponse(CamelModel):
    recent_users: list[AdminDashboardRecentUser]
    recent_contents: list[AdminDashboardRecentContent]
    recent_reports: list[AdminDashboardRecentReport]
