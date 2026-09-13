import uuid

from pydantic import Field

from api.core.schema import CamelModel
from api.images.jobs import ImageGenerationJobStatus
from api.images.models import AspectRatio, ImageModelId, ImageStylePreset

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
    prompt: str = Field(min_length=1)
    model: ImageModelId
    style: ImageStylePreset
    aspect_ratio: AspectRatio
    # local-image-gen-goal-prompt.md LG-7: 집 PC 1장당 약 30초 × 직렬(LG-6) — 4장이면 한 잡이
    # 큐를 120초 독점한다. 30초 실측 전 상한(4)을 낮춘 것이라 GPU가 바뀌면 다시 열 값이다.
    count: int = Field(default=1, ge=1, le=2)


class ImageStyleItem(CamelModel):
    id: str
    name: str


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
