"""Provider 무관 이미지 생성 인터페이스.

구현체는 provider별 파일에 있다(`local_image.py`, local-image-gen-goal-prompt.md LG-13으로
Cloudflare/Gemini 경로는 제거됨). 이 모듈은 `google.genai`를 import하지 않는다 — Gemini
구현을 여기로 되돌리지 말 것.

`ImageStylePreset`은 local-image-gen-techspec.md LT-4로 `api.images.models`로 옮겼다(id
옆이 라벨의 집이라는 이유 — 그 파일이 서버가 내리는 스타일 라벨도 함께 갖는다).
"""

import abc

# `as ImageStylePreset`는 mypy의 명시적 재export 요구(`--no-implicit-reexport`, strict
# 기본값) 때문이다 — `from api.llm.image import ImageStylePreset`로 이 이름을 쓰는 테스트가
# 아직 셋 있다(`test_images_capabilities_gate.py`/`test_images_generate_api.py`/
# `test_seed_image_prompts.py`). 그 셋의 import 줄을 전부 고치는 대신, 이 한 줄로 기존
# import 경로를 계속 유효하게 둔다.
from api.images.models import ImageStylePreset as ImageStylePreset


class ImageClient(abc.ABC):
    """Provider-agnostic 이미지 생성 인터페이스. 구현체(`LocalImageClient`)는 프롬프트·
    스타일·종횡비를 받아 (이미지 바이트, MIME 타입)을 반환한다. 잡 러너/라우터는 이 타입만 안다."""

    @abc.abstractmethod
    async def generate_image(
        self, prompt: str, style: ImageStylePreset, aspect_ratio: str
    ) -> tuple[bytes, str]:
        raise NotImplementedError
