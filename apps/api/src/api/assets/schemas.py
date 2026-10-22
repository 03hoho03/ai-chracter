import enum
import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from api.content.schemas import SITUATIONAL_IMAGE_TRIGGER_MAX_LENGTH
from api.core.schema import CamelModel
from api.db.models.content import ContentType
from api.db.models.media import AssetStatus


class AssetPurpose(str, enum.Enum):
    """Extend as new upload flows need a purpose."""

    PROFILE_IMAGE = "profile-image"
    CONTENT_THUMBNAIL = "content-thumbnail"
    SITUATIONAL_IMAGE = "situational-image"
    INQUIRY_ATTACHMENT = "inquiry-attachment"
    # 소설 화 삽화. 정지 그림만 받는다(완료 때 움직이는 그림은 거절). 소설 삽화 스위치가 켜졌을 때만 받는다.
    NOVEL_ILLUSTRATION = "novel-illustration"


# Per-purpose upload size limits in bytes, applied to the *resized* result the FE
# uploads — the normal path stays far
# below these, so the server-side check is purely a bypass safety net.
#
# ⚠️ This dict is `dict[AssetPurpose, int]`, not `Record<AssetPurpose, ...>` — mypy does
# NOT check dict-literal enum exhaustiveness here (verified with `uv run mypy --strict` on
# equivalent code: `Success: no issues found`). A missing key is a runtime KeyError → 500 in
# `assets/router.py`'s `_upload_size_limit` (it indexes directly, not `.get()`). The FE's two
# `Record<AssetPurpose, ...>` maps (`shared/lib/asset/uploadAsset.ts`) DO get compile-time
# exhaustiveness — this is the one spot only a human keeps in sync.
UPLOAD_SIZE_LIMIT_BYTES: dict[AssetPurpose, int] = {
    AssetPurpose.PROFILE_IMAGE: 2 * 1024 * 1024,
    AssetPurpose.CONTENT_THUMBNAIL: 5 * 1024 * 1024,
    AssetPurpose.SITUATIONAL_IMAGE: 5 * 1024 * 1024,
    AssetPurpose.INQUIRY_ATTACHMENT: 5 * 1024 * 1024,
    AssetPurpose.NOVEL_ILLUSTRATION: 5 * 1024 * 1024,
}


class UploadCrop(CamelModel):
    """원본 픽셀 좌표의 크롭 영역. 움직이는 대표 이미지(GIF)만 보낸다 — 화면의 크롭 모달은 canvas 로 한 장만 그려 움직임을
    지우므로, 원본은 그대로 올리고 영역만 받아 서버가 모든 프레임에 건다."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)


class PresignedUploadRequest(CamelModel):
    content_type: str = Field(min_length=1)
    purpose: AssetPurpose
    crop: UploadCrop | None = None


class PresignedUploadResponse(CamelModel):
    upload_url: str
    asset_id: uuid.UUID
    expires_at: datetime


class AssetCompleteResponse(CamelModel):
    asset_id: uuid.UUID
    status: AssetStatus


class RegisterSituationalImageRequest(CamelModel):
    entity_id: uuid.UUID
    content_version_id: uuid.UUID
    trigger_condition: str = Field(min_length=1, max_length=SITUATIONAL_IMAGE_TRIGGER_MAX_LENGTH)
    order: int


class SituationalImageResponse(CamelModel):
    entity_id: uuid.UUID
    image_asset_id: uuid.UUID
    blurred_asset_id: uuid.UUID
    trigger_condition: str
    order: int


GeneratedImageUsageField = Literal["thumbnail", "situationalImage", "mediaBook"]


class GeneratedImageUsage(CamelModel):
    """One content referencing a generated asset.

    Draft and published versions both count as "in use"; versions of the same
    content referencing the asset with the same field are merged into one entry.
    """

    content_id: uuid.UUID
    content_type: ContentType
    content_title: str
    field: GeneratedImageUsageField


NovelImageUsageField = Literal["cover", "illustration"]


class NovelImageUsage(CamelModel):
    """이 그림을 쓰는 소설 하나 — 표지이거나, 어느 화의 어느 개정(지난 판 포함)의 삽화다. 작품 사용처(`GeneratedImageUsage`)와
    칸을 나눈 것은 작품 사용처가 빌더로 가는 링크로 그려지기 때문이다."""

    novel_id: uuid.UUID
    novel_title: str
    field: NovelImageUsageField


class GeneratedImageItem(CamelModel):
    """`GET /me/generated-images` item shape."""

    asset_id: uuid.UUID
    image_url: str
    created_at: datetime
    usages: list[GeneratedImageUsage]
    novel_usages: list[NovelImageUsage]
