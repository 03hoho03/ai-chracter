from collections.abc import Callable
from functools import lru_cache
from typing import assert_never

from api.images.models import ImageModelId
from api.llm.client import LLMClient
from api.llm.cloudflare_image import CloudflareImageClient
from api.llm.gemini import GeminiLLMClient
from api.llm.image import ImageClient

_CF_FLUX_MODEL = "@cf/black-forest-labs/flux-1-schnell"
_CF_SDXL_MODEL = "@cf/stabilityai/stable-diffusion-xl-base-1.0"


@lru_cache
def get_llm_client() -> LLMClient:
    """FastAPI dependency: 서비스 로직은 이 함수를 통해서만 LLMClient를 얻는다.

    구체 구현체(GeminiLLMClient)를 직접 참조하지 않도록 하기 위한 DI 지점 —
    같은 이유로 만든 `api.auth.google_oauth.get_google_profile` 패턴과 동일.
    """
    return GeminiLLMClient()


def build_image_client(model_id: ImageModelId) -> ImageClient:
    """모델 id → 구체 ImageClient. FLUX/SDXL 모두 Cloudflare Workers AI를 쓰지만 요청/응답
    형식이 달라 별도 설정(send_dimensions)으로 구성한다. 새 모델 추가 시 여기 분기를
    안 늘리면 `assert_never`가 mypy 단계에서 잡는다."""
    if model_id == "flux-schnell":
        return CloudflareImageClient(_CF_FLUX_MODEL, send_dimensions=False)
    if model_id == "sdxl":
        return CloudflareImageClient(_CF_SDXL_MODEL, send_dimensions=True)
    assert_never(model_id)


def get_image_client() -> Callable[[ImageModelId], ImageClient]:
    """FastAPI dependency: 이미지 생성 라우터는 이 팩토리를 통해 모델별 ImageClient를
    얻는다 — 테스트에서 `app.dependency_overrides[get_image_client]`로 팩토리를 교체한다."""
    return build_image_client
