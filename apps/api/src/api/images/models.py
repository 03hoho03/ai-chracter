"""이미지 생성 모델 레지스트리 (tasks/prd-image-generation.md 확장 — 다중 모델 선택).

모델마다 지원 종횡비(capability)가 달라, FE가 이 목록을 받아 모델 선택 시 미지원
종횡비를 비활성화한다. BE도 `POST /images/generate`에서 같은 집합으로 방어 검증한다.
`AspectRatio`/`ImageModelId`를 여기 두어 schemas.py ↔ models.py 순환 import를 피한다.
"""

from dataclasses import dataclass
from typing import Literal

AspectRatio = Literal["1:1", "4:3", "3:4", "16:9", "9:16"]
ImageModelId = Literal["flux-schnell", "sdxl"]


@dataclass(frozen=True)
class ImageModelSpec:
    id: ImageModelId
    name: str
    # 이 모델이 실제로 만들 수 있는 종횡비. FLUX.1-schnell(Cloudflare)은 정사각형만
    # 지원하고, SDXL은 width/height 지정으로 전 종횡비를 낸다.
    supported_aspect_ratios: tuple[AspectRatio, ...]


IMAGE_MODELS: tuple[ImageModelSpec, ...] = (
    ImageModelSpec(id="flux-schnell", name="FLUX.1 schnell", supported_aspect_ratios=("1:1",)),
    ImageModelSpec(
        id="sdxl",
        name="Stable Diffusion XL",
        supported_aspect_ratios=("1:1", "4:3", "3:4", "16:9", "9:16"),
    ),
)

IMAGE_MODELS_BY_ID: dict[ImageModelId, ImageModelSpec] = {m.id: m for m in IMAGE_MODELS}
