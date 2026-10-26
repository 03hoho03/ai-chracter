import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from api.core.schema import CamelModel
from api.db.models.content import ContentVisibility, ModerationStatus
from api.db.models.novel import (
    NovelPublicationModerationStatus,
    NovelPublicationReviewStatus,
    NovelPublicationVisibility,
)
from api.novelize.schemas import NovelCover

WorkListType = Literal["all", "character", "story", "novel"]
# 초안 = 발행된 적 없음, 공개 중 = 독자에게 지금 보임, 수정본 있음 = 발행작의 고친 초안, 심사 중 = 소설 첫 공개 승인 대기.
# 판정식은 `router.py` 의 `list_my_works` docstring.
WorkListStatus = Literal["all", "draft", "public", "changed", "review"]


class ContentWorkItem(CamelModel):
    """캐릭터·스토리 한 줄. `title`·`thumbnail_url` 은 작가가 고치고 있는 초안 버전의 것이라, 수정본이 있는 발행작은 발행본과
    다를 수 있다. 수정본 있음 표시는 `has_published` ∧ `has_unpublished_changes` 다."""

    kind: Literal["character", "story"]
    id: uuid.UUID
    title: str
    thumbnail_url: str | None
    edited_at: datetime
    has_published: bool
    visibility: ContentVisibility
    moderation_status: ModerationStatus
    has_unpublished_changes: bool
    view_count: int
    chat_count: int
    like_count: int


class NovelWorkPublication(CamelModel):
    """소설의 노벨 공개 상태. `readable` 은 독자가 지금 읽을 수 있는가이고, 화면의 "공개 중" 표시와 목록의 공개 중 필터가
    이 값 하나를 본다 — 승인된 공개라도 원작 이용제한·공개 화 없음·게시자 정지·판매 중단이면 거짓이다."""

    visibility: NovelPublicationVisibility
    review_status: NovelPublicationReviewStatus | None
    moderation_status: NovelPublicationModerationStatus
    readable: bool


class NovelWorkItem(CamelModel):
    """소설 한 줄. `edited_at` 은 소설의 `updated_at` 이다. 공개한 적 없으면 `publication` 이 null 이다."""

    kind: Literal["novel"]
    id: uuid.UUID
    title: str | None
    content_title: str
    character_name: str | None
    cover: NovelCover
    chapter_count: int
    edited_at: datetime
    publication: NovelWorkPublication | None


WorkItem = Annotated[ContentWorkItem | NovelWorkItem, Field(discriminator="kind")]


class WorkListResponse(CamelModel):
    items: list[WorkItem]
    next_cursor: str | None
