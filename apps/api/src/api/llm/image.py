import enum

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from api.core.config import settings
from api.llm.client import LLMClientError, LLMPolicyViolationError

# Mirrors gemini.py's _POLICY_FINISH_REASONS: finish_reason values meaning
# Gemini's safetySettings blocked the output.
_POLICY_FINISH_REASONS = frozenset(
    {genai_types.FinishReason.SAFETY, genai_types.FinishReason.PROHIBITED_CONTENT}
)


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


def _apply_style_preset(prompt: str, style: ImageStylePreset) -> str:
    suffix = STYLE_PRESET_PROMPT_SUFFIXES[style]
    if not suffix:
        return prompt
    return f"{prompt}, {suffix}"


class GeminiImageClient:
    """이미지 생성 전용 Gemini 클라이언트 (tasks/prd-image-generation.md §3/§8).

    채팅용 GeminiLLMClient(gemini.py)와 같은 API 키를 쓰지만, 스트리밍 대화/판단
    호출과 섞이지 않도록 독립된 클래스로 분리했다(향후 이미지 전용 키 분리 시
    이 클래스만 바꾸면 되는 경계).
    """

    def __init__(self, api_key: str | None = None, model_name: str | None = None) -> None:
        self._client = genai.Client(api_key=api_key if api_key is not None else settings.gemini_api_key)
        self._model_name = model_name if model_name is not None else settings.gemini_image_model_name

    async def generate_image(self, prompt: str, style: ImageStylePreset, aspect_ratio: str) -> tuple[bytes, str]:
        full_prompt = _apply_style_preset(prompt, style)
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model_name,
                contents=full_prompt,
                config=genai_types.GenerateContentConfig(
                    image_config=genai_types.ImageConfig(aspect_ratio=aspect_ratio),
                ),
            )
        except (genai_errors.APIError, httpx.HTTPError) as exc:
            raise LLMClientError(f"Gemini image generation call failed: {exc}") from exc

        prompt_feedback = response.prompt_feedback
        if prompt_feedback is not None and prompt_feedback.block_reason is not None:
            raise LLMPolicyViolationError("Gemini blocked the image prompt via safetySettings")

        for candidate in response.candidates or []:
            if candidate.finish_reason in _POLICY_FINISH_REASONS:
                raise LLMPolicyViolationError("Gemini blocked the image output via safetySettings")
            content = candidate.content
            if content is None:
                continue
            for part in content.parts or []:
                inline_data = part.inline_data
                if inline_data is None:
                    continue
                data = inline_data.data
                if not data:
                    continue
                mime_type = inline_data.mime_type or "image/png"
                return data, mime_type

        raise LLMClientError("Gemini image response contained no image data")
