import uuid

from pydantic import Field

from api.core.schema import CamelModel
from api.images.jobs import ImageGenerationJobStatus
from api.images.models import AspectRatio, ImageModelId
from api.llm.image import ImageStylePreset

__all__ = [
    "AspectRatio",
    "GenerateImageRequest",
    "GenerateImageResponse",
    "ImageJobImageItem",
    "ImageJobStatusResponse",
    "ImageModelItem",
]


class GenerateImageRequest(CamelModel):
    prompt: str = Field(min_length=1)
    model: ImageModelId
    style: ImageStylePreset
    aspect_ratio: AspectRatio
    count: int = Field(default=1, ge=1, le=4)


class ImageModelItem(CamelModel):
    id: ImageModelId
    name: str
    supported_aspect_ratios: list[AspectRatio]


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
