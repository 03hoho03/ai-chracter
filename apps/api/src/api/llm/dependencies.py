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
    같은 이유로 만든 `api.auth.google_oauth.get_google_profile_fetcher` 패턴과 동일. 돌려주는 것은 고른 모델에 따라
    Gemini·Bedrock 구현으로 나눠 보내는 라우팅 클라이언트다(`llm/routing.py`).

    import 을 함수 안에 두어도 `google.genai`·`anthropic` 의 import 비용은 지금 모든 프로세스가 기동 때 낸다.
    `core/sentry.py` 가 모듈 최상단에서 `GoogleGenAIIntegration`·`AnthropicIntegration` 을 import 하고, 두 통합 모듈은
    import 되는 순간 `google.genai`·`anthropic` 을 끌어온다(DSN 이 비어 있어도). DSN 이 있으면 `sentry_sdk.init()` 도
    auto-enabling 통합 목록 전체를 import 하므로 `disabled_integrations` 에 넣어도 같다. 개발 맥에서
    `python -X importtime -c "import api.main"` 로 잰 값은 (따뜻한 캐시 4회) `api.main` 2.0~2.4초 중 `anthropic` 약 0.5초·
    `google.genai` 약 0.56~0.73초, 첫 회(차가운 캐시)는 3.2초 중 각각 1.0초·0.78초였다 — 이 함수가 import 하는
    `api.llm.gemini`·`api.llm.routing` 자체는 그 뒤로 1ms 안팎이다. 이 비용을 기동에서 빼는 길은 Sentry 를
    `auto_enabling_integrations=False` 와 명시 통합 목록으로 초기화하고 `core/sentry.py` 의 최상단 import 를 없애는
    것뿐이다.

    Gemini 클라이언트는 지금처럼 여기서 바로 만든다 — 키가 없을 때의 `ValueError` 가 라우트 본문(SSE 제너레이터) 밖인
    의존성 해석 시점에 나야 한다. Bedrock 클라이언트는 라우팅 클라이언트가 첫 상위 모델 호출 때 만든다.
    """
    from api.llm.gemini import GeminiLLMClient
    from api.llm.routing import RoutingLLMClient

    return RoutingLLMClient(GeminiLLMClient())


def build_image_client(model_id: ImageModelId) -> ImageClient:
    """모델 id → 구체 ImageClient. 집 PC로 전환한 뒤에도
    `assert_never` 분기 형태를 유지한다 — 체크포인트가 늘 때 분기 누락을 mypy가 잡는 성질이
    로컬 전환(여러 체크포인트 예정)에서 더 필요해진다."""
    if model_id == "v1":
        return LocalImageClient(model_id)
    assert_never(model_id)


def get_image_client() -> Callable[[ImageModelId], ImageClient]:
    """FastAPI dependency: 이미지 생성 라우터는 이 팩토리를 통해 모델별 ImageClient를
    얻는다 — 테스트에서 `app.dependency_overrides[get_image_client]`로 팩토리를 교체한다."""
    return build_image_client
