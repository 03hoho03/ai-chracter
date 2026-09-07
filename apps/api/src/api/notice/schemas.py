import uuid
from datetime import datetime

from api.core.schema import CamelModel


class NoticeListItem(CamelModel):
    id: uuid.UUID
    title: str
    published_at: datetime


class NoticeListResponse(CamelModel):
    items: list[NoticeListItem]


class NoticeDetailResponse(CamelModel):
    id: uuid.UUID
    title: str
    body_markdown: str
    published_at: datetime


class AdminNoticeListItem(CamelModel):
    id: uuid.UUID
    title: str
    published: bool
    published_at: datetime | None
    created_at: datetime


class AdminNoticeListResponse(CamelModel):
    items: list[AdminNoticeListItem]
    page: int
    total_pages: int
    total_count: int


class AdminNoticeDetailResponse(CamelModel):
    id: uuid.UUID
    title: str
    body_markdown: str
    published: bool
    published_at: datetime | None
    created_at: datetime


class AdminNoticeCreateRequest(CamelModel):
    title: str
    body_markdown: str


class AdminNoticeUpdateRequest(CamelModel):
    title: str | None = None
    body_markdown: str | None = None
