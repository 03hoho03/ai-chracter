import uuid
from datetime import datetime

from pydantic import Field

from api.core.schema import CamelModel
from api.db.models.inquiry import InquiryCategory, InquiryStatus


class InquiryCreateRequest(CamelModel):
    category: InquiryCategory
    # ⚠️ max_length 100/2000은 FE zod 스키마(`inquiries/new` 폼)와 같은 값이어야 한다 —
    # 어긋나면 화면은 통과시키고 서버가 422로 거절한다.
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=2000)
    attachment_asset_id: uuid.UUID | None = None


class InquiryCreateResponse(CamelModel):
    id: uuid.UUID


class MyInquiryListItem(CamelModel):
    id: uuid.UUID
    category: InquiryCategory
    title: str
    status: InquiryStatus
    created_at: datetime


class MyInquiryListResponse(CamelModel):
    items: list[MyInquiryListItem]


class MyInquiryDetailResponse(CamelModel):
    id: uuid.UUID
    category: InquiryCategory
    title: str
    body: str
    attachment_url: str | None  # presigned GET
    status: InquiryStatus
    reply_body: str | None  # plain text (D-19)
    answered_at: datetime | None
    created_at: datetime


class AdminInquiryListItem(CamelModel):
    id: uuid.UUID
    category: InquiryCategory
    title: str
    status: InquiryStatus
    created_at: datetime


class AdminInquiryListResponse(CamelModel):
    items: list[AdminInquiryListItem]
    page: int
    total_pages: int
    total_count: int


class AdminInquiryDetailResponse(CamelModel):
    id: uuid.UUID
    category: InquiryCategory
    title: str
    body: str
    attachment_url: str | None  # presigned GET
    status: InquiryStatus
    author_nickname: str
    author_email: str
    reply_body: str | None
    answered_at: datetime | None
    created_at: datetime


class AdminInquiryReplyRequest(CamelModel):
    reply_body: str = Field(min_length=1)
