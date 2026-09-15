import uuid

from pydantic import Field

from api.core.schema import CamelModel
from api.images.jobs import ImageGenerationJobStatus
from api.images.models import AspectRatio, ImageBlockedReason, ImageInputError, ImageModelId, ImageStylePreset

__all__ = [
    "AspectRatio",
    "GenerateImageRequest",
    "GenerateImageResponse",
    "ImageJobImageItem",
    "ImageJobStatusResponse",
    "ImageModelItem",
    "ImageStyleItem",
]


class GenerateImageRequest(CamelModel):
    # image-style-7-goal-prompt.md IS-7 / local-image-gen-contract.md LC-11: 집 PC 계약 v3가
    # 통보한 1000자 하드 상한을 미러한다 — 값은 구현 단계 실측으로 재확인 대상이고 바뀌면 계약
    # 개정으로 통지된다. FE 미러: apps/web/src/features/generate-images/model/schema.ts.
    prompt: str = Field(min_length=1, max_length=1000)
    model: ImageModelId
    style: ImageStylePreset
    aspect_ratio: AspectRatio
    # local-image-gen-goal-prompt.md LG-7: 집 PC 1장당 약 30초 × 직렬(LG-6) — 4장이면 한 잡이
    # 큐를 120초 독점한다. 30초 실측 전 상한(4)을 낮춘 것이라 GPU가 바뀌면 다시 열 값이다.
    count: int = Field(default=1, ge=1, le=2)


class ImageStyleItem(CamelModel):
    id: str
    name: str
    # image-refact-techspec.md IT-2 — 목록에서 빼지 않고 플래그로 표현한다. 모델의
    # `available`과 같은 근거다(LT-5): 빈 목록은 "그런 스타일이 없다"와 "지금 못
    # 쓴다"를 구분하지 못한다.
    available: bool


class ImageModelItem(CamelModel):
    id: ImageModelId
    name: str
    supported_aspect_ratios: list[AspectRatio]
    # local-image-gen-techspec.md LT-5: 목록에서 빼지 않고 플래그로 표현한다 — 빈 배열은
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
    # guard-techspec.md GT-4: `ImageBlockedReason`가 `Literal`이라 `generated.ts`에
    # 유니온으로 내려가 FE가 exhaustive switch를 쓸 수 있다(guard-goal-prompt.md G-6).
    blocked_count: int
    blocked_reason: ImageBlockedReason | None
    # image-style-7-goal-prompt.md IS-8: 사용자가 프롬프트를 고쳐야 하는 입력 오류
    # 축 — `blocked_reason`과 별개 필드로 둔다(그 필드의 "사유를 숨긴다" 의미를
    # 보존하기 위해서다, IS-8 근거).
    input_error_count: int
    input_error: ImageInputError | None
