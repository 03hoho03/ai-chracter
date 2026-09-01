"""Provider 무관 이미지 생성 인터페이스와 스타일 프리셋.

구현체는 provider별 파일에 있다(`cloudflare_image.py`/`gemini_image.py`). 이 모듈은
`google.genai`를 import하지 않는다 — 그래야 Cloudflare만 쓰는 기동 경로가 genai import
비용(1 vCPU에서 약 1초)을 물지 않는다. Gemini 구현을 여기로 되돌리지 말 것.
"""

import abc
import enum


class ImageStylePreset(str, enum.Enum):
    REALISTIC = "realistic"
    ANIME = "anime"
    ILLUSTRATION = "illustration"
    RENDER3D = "render3d"
    NONE = "none"


# tasks/prd-image-generation.md §3: 프리셋별 프롬프트 부착 문구 (영어). NONE은 부착하지 않는다.
STYLE_PRESET_PROMPT_SUFFIXES: dict[ImageStylePreset, str] = {
    ImageStylePreset.REALISTIC: "photorealistic, realistic lighting, high detail",
    ImageStylePreset.ANIME: "anime style, cel shading, clean lineart",
    ImageStylePreset.ILLUSTRATION: "digital illustration, painterly, soft shading",
    ImageStylePreset.RENDER3D: "3D render, cinematic lighting, volumetric",
    ImageStylePreset.NONE: "",
}


def apply_style_preset(prompt: str, style: ImageStylePreset) -> str:
    suffix = STYLE_PRESET_PROMPT_SUFFIXES[style]
    if not suffix:
        return prompt
    return f"{prompt}, {suffix}"


class ImageClient(abc.ABC):
    """Provider-agnostic 이미지 생성 인터페이스. 구현체(Gemini/Cloudflare)는 프롬프트·스타일·
    종횡비를 받아 (이미지 바이트, MIME 타입)을 반환한다. 잡 러너/라우터는 이 타입만 안다."""

    @abc.abstractmethod
    async def generate_image(
        self, prompt: str, style: ImageStylePreset, aspect_ratio: str
    ) -> tuple[bytes, str]:
        raise NotImplementedError
