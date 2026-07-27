from functools import lru_cache

from api.llm.client import LLMClient
from api.llm.gemini import GeminiLLMClient
from api.llm.image import GeminiImageClient


@lru_cache
def get_llm_client() -> LLMClient:
    """FastAPI dependency: 서비스 로직은 이 함수를 통해서만 LLMClient를 얻는다.

    구체 구현체(GeminiLLMClient)를 직접 참조하지 않도록 하기 위한 DI 지점 —
    같은 이유로 만든 `api.auth.google_oauth.get_google_profile` 패턴과 동일.
    """
    return GeminiLLMClient()


@lru_cache
def get_image_client() -> GeminiImageClient:
    """FastAPI dependency: 이미지 생성 라우터는 이 함수를 통해서만 GeminiImageClient를
    얻는다 — 테스트에서 `app.dependency_overrides`로 교체 가능하게 하기 위한 DI 지점."""
    return GeminiImageClient()
