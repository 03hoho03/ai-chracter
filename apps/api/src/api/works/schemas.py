import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from api.core.schema import CamelModel, NoNul
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


# 묶음 이름 한도의 권위는 BE 다(화면의 40자는 사본). 앞뒤 공백을 먼저 떼고 재므로 공백만인 이름은 0자로 거부된다. 같은 이름은
# 허용한다.
WORK_BUNDLE_NAME_MAX_LENGTH = 40
WorkBundleName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=WORK_BUNDLE_NAME_MAX_LENGTH), NoNul
]
# 묶음에 넣는 작품의 종류. 캐릭터·스토리는 `contents`, 소설은 `novels` 행이다.
WorkBundleKind = Literal["character", "story", "novel"]


class WorkBundleNameRequest(CamelModel):
    name: WorkBundleName


class WorkBundleCreatedResponse(CamelModel):
    id: uuid.UUID


class WorkBundleSummary(CamelModel):
    """묶음 하나. `item_count` 는 `GET /me/works?bundleId=` 가 내는 항목 수와 같다(운영 삭제된 작품·숨긴 소설, 소설화 허용이
    없는 계정의 소설은 빠진다). `contains_work` 는 목록 요청에 `kind`·`workId` 를 줬을 때만 참·거짓이고 아니면 null 이다."""

    id: uuid.UUID
    name: str
    item_count: int
    updated_at: datetime
    contains_work: bool | None


class WorkBundleListResponse(CamelModel):
    items: list[WorkBundleSummary]
