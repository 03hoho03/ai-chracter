from collections.abc import Callable
from functools import lru_cache
from typing import assert_never

from api.images.models import ImageModelId
from api.llm.client import LLMClient
from api.llm.image import ImageClient
from api.llm.local_image import LocalImageClient


@lru_cache
def get_llm_client() -> LLMClient:
    """FastAPI dependency: 서비스 로직은 이 함수를 통해서만 LLMClient를 얻는다.

    구체 구현체(GeminiLLMClient)를 직접 참조하지 않도록 하기 위한 DI 지점 —
    같은 이유로 만든 `api.auth.google_oauth.get_google_profile` 패턴과 동일.

    import이 함수 안에 있는 건 프로세스 기동(재배포·재시작·크래시 복구) 비용 때문이다:
    `api.llm.gemini`가 끌고 오는 `google.genai`는 import에만 약 1초가 든다(1 vCPU 실측).
    여기 두면 그 비용을 기동 시점이 아니라 첫 LLM 호출 시점(`@lru_cache`라 프로세스당 한
    번)에 문다 — 홈/목록 같은 LLM 무관 경로만 타는 프로세스는 이 비용을 아예 안 낸다.
    모듈 최상단으로 올리지 말 것.
    """
    from api.llm.gemini import GeminiLLMClient

    return GeminiLLMClient()


def build_image_client(model_id: ImageModelId) -> ImageClient:
    """모델 id → 구체 ImageClient. local-image-gen-techspec.md LT-7: 집 PC로 전환한 뒤에도
    `assert_never` 분기 형태를 유지한다 — 체크포인트가 늘 때 분기 누락을 mypy가 잡는 성질이
    로컬 전환(여러 체크포인트 예정, local-image-gen-goal-prompt.md LG-9)에서 더 필요해진다."""
    if model_id == "v1":
        return LocalImageClient(model_id)
    assert_never(model_id)


def get_image_client() -> Callable[[ImageModelId], ImageClient]:
    """FastAPI dependency: 이미지 생성 라우터는 이 팩토리를 통해 모델별 ImageClient를
    얻는다 — 테스트에서 `app.dependency_overrides[get_image_client]`로 팩토리를 교체한다."""
    return build_image_client
