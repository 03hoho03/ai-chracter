import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from api.admin.schemas import ChatViewReasonCategory
from api.core.schema import CamelModel
from api.images.jobs import ImageGenerationJobStatus
from api.images.models import AspectRatio, ImageBlockedReason, ImageInputError, ImageModelId, ImageStylePreset

__all__ = [
    "AdminImageGenerationDetailItem",
    "AdminImageGenerationDetailListResponse",
    "AdminImageGenerationImageItem",
    "AdminImageGenerationListItem",
    "AdminImageGenerationListResponse",
    "AdminImageGenerationViewRequest",
    "AspectRatio",
    "GenerateImageRequest",
    "GenerateImageResponse",
    "ImageGenerationRequestStatus",
    "ImageJobImageItem",
    "ImageJobStatusResponse",
    "ImageModelItem",
    "ImageStyleItem",
]

# 요청 종료 상태 판정 규칙의 값 그대로. 응답 필드는
# DB 컬럼(plain Text — 값이 늘 때 마이그레이션 없이 넓히기 위해서)을 그대로 str로 받지만, 어드민 목록의 `status` 쿼리
# 필터만은 잘못된 값을 400 대신 422로 걸러내도록 이 Literal로 좁힌다.
ImageGenerationRequestStatus = Literal["pending", "succeeded", "blocked", "failed"]


class GenerateImageRequest(CamelModel):
    # 집 PC 계약 v3가
    # 통보한 1000자 하드 상한을 미러한다 — 값은 구현 단계 실측으로 재확인 대상이고 바뀌면 계약
    # 개정으로 통지된다. FE 미러: apps/web/src/features/generate-images/model/schema.ts.
    prompt: str = Field(min_length=1, max_length=1000)
    model: ImageModelId
    style: ImageStylePreset
    aspect_ratio: AspectRatio
    # 집 PC 1장당 약 30초 × 직렬 — 4장이면 한 잡이
    # 큐를 120초 독점한다. 30초 실측 전 상한(4)을 낮춘 것이라 GPU가 바뀌면 다시 열 값이다.
    count: int = Field(default=1, ge=1, le=2)


class ImageStyleItem(CamelModel):
    id: str
    name: str
    # 목록에서 빼지 않고 플래그로 표현한다. 모델의
    # `available`과 같은 근거다: 빈 목록은 "그런 스타일이 없다"와 "지금 못
    # 쓴다"를 구분하지 못한다.
    available: bool


class ImageModelItem(CamelModel):
    id: ImageModelId
    name: str
    supported_aspect_ratios: list[AspectRatio]
    # 목록에서 빼지 않고 플래그로 표현한다 — 빈 배열은
    # "모델이 없다"와 "지금 못 쓴다"를 구분하지 못한다.
    available: bool
    styles: list[ImageStyleItem]


class GenerateImageResponse(CamelModel):
    job_id: str


class ImageJobImageItem(CamelModel):
    asset_id: uuid.UUID
    image_url: str


class ImageJobStatusResponse(CamelModel):
    status: ImageGenerationJobStatus
    requested_count: int
    completed_count: int
    images: list[ImageJobImageItem]
    error: str | None
    # `ImageBlockedReason`가 `Literal`이라 `generated.ts`에
    # 유니온으로 내려가 FE가 exhaustive switch를 쓸 수 있다.
    blocked_count: int
    blocked_reason: ImageBlockedReason | None
    # 사용자가 프롬프트를 고쳐야 하는 입력 오류
    # 축 — `blocked_reason`과 별개 필드로 둔다(그 필드의 "사유를 숨긴다" 의미를
    # 보존하기 위해서다).
    input_error_count: int
    input_error: ImageInputError | None


# ---- 어드민 ------------------------------------------------------------------------
# notice·inquiry와 같은 패턴 — 공개 도메인이 이미 있는 리소스라 Admin* 스키마는
# 전용 admin 패키지가 아니라 이 도메인의 schemas.py에 둔다.


class AdminImageGenerationListItem(CamelModel):
    """전역 목록은 메타데이터만 — 프롬프트 문자열과 이미지 URL을 싣지 않는다."""

    id: uuid.UUID
    user_id: uuid.UUID
    nickname: str
    email: str
    # `ImageGenerationRequest.status`/`.style`처럼 plain Text 컬럼 그대로 str로 받는다 —
    # Literal/enum으로 좁히면 DB 컬럼이 Text를 고른 이유(값이 늘 때 마이그레이션 없이 넓히기)가
    # API 응답 스키마에서 다시 막힌다.
    status: str
    style: str
    requested_count: int
    completed_count: int
    created_at: datetime


class AdminImageGenerationListResponse(CamelModel):
    items: list[AdminImageGenerationListItem]
    page: int
    total_pages: int
    total_count: int


class AdminImageGenerationViewRequest(CamelModel):
    """`admin/chat_view.py`의 `AdminChatRoomViewRequest`와 같은 모양이지만, 사유
    enum은 그 클래스를 통째로 재사용하지 않고 `ChatViewReasonCategory`만 재사용한다."""

    reason_category: ChatViewReasonCategory
    reason_text: str


class AdminImageGenerationImageItem(CamelModel):
    asset_id: uuid.UUID
    image_url: str


class AdminImageGenerationDetailItem(CamelModel):
    """사유 게이트를 통과한 뒤에만 내려간다 — 프롬프트와 이미지 URL이 들어간다."""

    id: uuid.UUID
    prompt: str
    # 위 `AdminImageGenerationListItem.style`/`.status`와 같은 이유 — 전부 plain
    # Text 컬럼이라 Literal/enum으로 좁히지 않는다.
    style: str
    aspect_ratio: str
    model: str
    status: str
    requested_count: int
    completed_count: int
    blocked_count: int
    blocked_reason: str | None
    input_error_count: int
    input_error: str | None
    error: str | None
    created_at: datetime
    images: list[AdminImageGenerationImageItem]


class AdminImageGenerationDetailListResponse(CamelModel):
    items: list[AdminImageGenerationDetailItem]
    page: int
    total_pages: int
    total_count: int
