from typing import Literal

from pydantic import Field

from api.core.schema import CamelModel
from api.llm.image import ImageStylePreset

AspectRatio = Literal["1:1", "4:3", "3:4", "16:9", "9:16"]


class GenerateImageRequest(CamelModel):
    prompt: str = Field(min_length=1)
    style: ImageStylePreset
    aspect_ratio: AspectRatio
    count: int = Field(default=1, ge=1, le=4)


class GenerateImageResponse(CamelModel):
    job_id: str
