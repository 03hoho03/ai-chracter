"""Cloudflare Workers AI 이미지 생성 클라이언트 (무료 티어, 10k neurons/일).

FLUX.1-schnell / SDXL를 같은 REST 엔드포인트로 호출한다. 두 모델의 응답 형식이 달라
(FLUX=base64 JSON, SDXL=binary image) content-type으로 분기한다. `GeminiImageClient`와
같은 `ImageClient` 인터페이스라, 잡 러너/라우터 코드는 provider를 신경 쓰지 않는다.
"""

import base64
import io

import httpx

from api.core.config import settings
from api.llm.client import LLMClientError
from api.llm.image import ImageClient, ImageStylePreset, apply_style_preset

# SDXL은 width/height를 직접 받는다(256~2048). 예전 값은 긴 변을 1024로 고정해 매핑했는데
# 그러면 9:16 같은 세로 비율이 576×1024=0.59M px로 SDXL 학습 면적(≈1.05M)의 56%에 그쳐
# 품질이 떨어졌다. 아래 값은 비율을 정확히 유지한 채 면적을 ≈1.05M로 올린 것이며 전부 8의
# 배수다. `2:3`만 예외로 832×1216(=13:19)을 쓴다 — Animagine XL 4.0 모델카드 권장
# 버킷이자 NovelAI 기본값이라 학습치 일치를 비율 정확도보다 위에 뒀다(의도된 근사치다).
# CSS 표시 슬롯은 정확한 2:3이고, object-cover가 높이를 맞추므로 생성물에서 가로
# **2.56%**(832px 중 21.3px)가 잘린다 = 1 - (2/3)/(832/1216).
# ⚠️ 이 수치를 `832/1216 ÷ 2/3 - 1 = 2.63%`로 "고치지 말 것" — 그건 슬롯 대비 **초과분**이지
# 원본에서 잘려 나가는 몫이 아니다(적대적 리뷰가 실제로 이 둘을 혼동했다).
# 근거: card-grid-goal-prompt.md D-2 · card-grid-techspec.md T-7.
# ImageClient.generate_image의 aspect_ratio가 str이라 str 키로 둔다(미지원 값은 기본 정사각).
_ASPECT_TO_WH: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "4:3": (1184, 888),
    "3:4": (888, 1184),
    "16:9": (1408, 792),
    "9:16": (792, 1408),
    "2:3": (832, 1216),
}


def _is_blank_image(data: bytes) -> bool:
    """Cloudflare's built-in safety filter doesn't error on a flagged prompt — it silently
    swaps the output for a solid single-color (usually black) image instead. Detect that
    case so it surfaces as a failure rather than a "successful" empty result. Any decode
    failure is left to the normal image-handling path, not treated as blank.
    """
    # import이 함수 안에 있는 이유는 `assets/image_processing.py`와 같다 — Pillow는
    # import에만 3.7MB를 읽는데 이 모듈은 `llm/dependencies.py`를 타고 모든 기동
    # 경로에 걸려 있다. 최상단으로 올리지 말 것.
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as img:
            colors = img.convert("RGB").getcolors(maxcolors=2)
    except Exception:
        return False
    return colors is not None and len(colors) == 1


class CloudflareImageClient(ImageClient):
    def __init__(
        self,
        cf_model: str,
        *,
        send_dimensions: bool,
        account_id: str | None = None,
        api_token: str | None = None,
    ) -> None:
        self._cf_model = cf_model
        # FLUX는 width/height 파라미터가 없어(정사각 고정) 차원을 보내지 않는다.
        self._send_dimensions = send_dimensions
        self._account_id = account_id if account_id is not None else settings.cloudflare_account_id
        self._api_token = api_token if api_token is not None else settings.cloudflare_api_token

    async def generate_image(
        self, prompt: str, style: ImageStylePreset, aspect_ratio: str
    ) -> tuple[bytes, str]:
        full_prompt = apply_style_preset(prompt, style)
        body: dict[str, object] = {"prompt": full_prompt}
        if self._send_dimensions:
            width, height = _ASPECT_TO_WH.get(aspect_ratio, (1024, 1024))
            body["width"] = width
            body["height"] = height

        url = f"https://api.cloudflare.com/client/v4/accounts/{self._account_id}/ai/run/{self._cf_model}"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    url, headers={"Authorization": f"Bearer {self._api_token}"}, json=body
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMClientError(
                f"Cloudflare image generation failed: {exc.response.status_code} {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMClientError(f"Cloudflare image generation call failed: {exc}") from exc

        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            # FLUX: {"result": {"image": "<base64 JPEG>"}, "success": true}
            result = response.json().get("result") or {}
            encoded = result.get("image")
            if not encoded:
                raise LLMClientError("Cloudflare image response contained no image data")
            data, mime = base64.b64decode(encoded), "image/jpeg"
        else:
            # SDXL 등: 이미지 바이트를 그대로 반환
            data = response.content
            if not data:
                raise LLMClientError("Cloudflare image response was empty")
            mime = content_type or "image/png"

        if _is_blank_image(data):
            raise LLMClientError(
                "Cloudflare returned a blank single-color image — the prompt was likely "
                "flagged by the provider's built-in safety filter"
            )
        return data, mime
