from collections.abc import Callable
from functools import lru_cache
from typing import assert_never

from api.images.models import ImageModelId
from api.llm.client import LLMClient
from api.llm.cloudflare_image import CloudflareImageClient
from api.llm.image import ImageClient

_CF_FLUX_MODEL = "@cf/black-forest-labs/flux-1-schnell"
_CF_SDXL_MODEL = "@cf/stabilityai/stable-diffusion-xl-base-1.0"


@lru_cache
def get_llm_client() -> LLMClient:
    """FastAPI dependency: 서비스 로직은 이 함수를 통해서만 LLMClient를 얻는다.

    구체 구현체(GeminiLLMClient)를 직접 참조하지 않도록 하기 위한 DI 지점 —
    같은 이유로 만든 `api.auth.google_oauth.get_google_profile` 패턴과 동일.

    import이 함수 안에 있는 건 콜드스타트 때문이다: `api.llm.gemini`가 끌고 오는
    `google.genai`는 1 vCPU에서 import에만 약 1초가 든다. 여기 두면 그 비용을 기동
    시점이 아니라 첫 LLM 호출 시점(`@lru_cache`라 프로세스당 한 번)에 문다 — 홈/목록
    같은 LLM 무관 경로가 첫 요청인 콜드스타트는 이 비용을 아예 안 낸다.
    모듈 최상단으로 올리지 말 것.
    """
    from api.llm.gemini import GeminiLLMClient

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
