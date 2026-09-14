"""이미지 생성 모델 레지스트리 (tasks/archive/prd-image-generation.md 확장 — 다중 모델 선택,
local-image-gen-techspec.md LT-4로 로컬 자가 호스팅 체제 전환).

`AspectRatio`/`ImageModelId`/`ImageStylePreset`을 여기 두어 schemas.py ↔ models.py 순환
import를 피한다(스타일도 서버가 라벨을 내리므로 id 옆이 라벨의 집이다 — LT-4).

`supported_aspect_ratios`는 더 이상 이 파일의 정적 선언이 아니다 — 그 값의 출처가 집 PC의
capabilities 응답으로 옮겨갔다(local-image-gen-goal-prompt.md LG-4/LG-9). 이 레지스트리는
**불투명 id + 표시명만** 갖는다. 가용성과 지원 목록은 `api/llm/local_image.py`의
`LocalCapabilities`와 `api/images/router.py`의 교차 로직이 채운다.
"""

import enum
from dataclasses import dataclass
from typing import Literal

AspectRatio = Literal["1:1", "4:3", "3:4", "16:9", "9:16", "2:3"]
# local-image-gen-goal-prompt.md LG-9: 실제 체크포인트를 유추할 수 없는 중립 라벨.
# LG-16: 첫 런은 단일 모델("v1")로 시작한다.
ImageModelId = Literal["v1"]

# guard-contract.md LC-4a / guard-techspec.md GT-1: 집 PC의 두 가드(생성 전 프롬프트,
# 생성 후 이미지)가 422로 실어 보내는 고정 카테고리. 여기 두는 이유는 위 순환 회피와
# 같다 — `llm/local_image.py`(예외)·`images/jobs.py`(Redis 모델)·`images/schemas.py`
# (응답) 셋이 같은 리터럴을 공유해야 한다.
ImageBlockedReason = Literal["prompt", "image"]


class ImageStylePreset(str, enum.Enum):
    # image-style-7-goal-prompt.md IS-1: 계약 v3가 지정한 7종, id·순서 그대로.
    # 별칭 없음 — 기존 4종(base/line/water/real)은 전부 폐기됐다.
    SOFT_PORTRAIT = "soft_portrait"  # 부드러운
    CHAPEL_GLASS = "chapel_glass"  # 스테인드
    ROYAL_DRAMA = "royal_drama"  # 극적
    SPARKLE_NIGHT = "sparkle_night"  # 반짝임
    WATERCOLOR = "watercolor"  # 수채
    PIXEL_ART = "pixel_art"  # 픽셀
    DECO_CUTE = "deco_cute"  # 데포르메


@dataclass(frozen=True)
class ImageModelSpec:
    id: ImageModelId
    name: str


IMAGE_MODELS: tuple[ImageModelSpec, ...] = (ImageModelSpec(id="v1", name="v1"),)
IMAGE_MODELS_BY_ID: dict[ImageModelId, ImageModelSpec] = {m.id: m for m in IMAGE_MODELS}


@dataclass(frozen=True)
class ImageStyleSpec:
    id: str
    name: str


# image-style-7-goal-prompt.md IS-1/IS-3: 순서가 곧 `GET /images/models`의 응답
# 순서다. 표시명의 유일한 소스가 여기다(집 PC capabilities는 id 문자열만 준다).
IMAGE_STYLE_PRESETS: tuple[ImageStyleSpec, ...] = (
    ImageStyleSpec(id="soft_portrait", name="부드러운"),
    ImageStyleSpec(id="chapel_glass", name="스테인드"),
    ImageStyleSpec(id="royal_drama", name="극적"),
    ImageStyleSpec(id="sparkle_night", name="반짝임"),
    ImageStyleSpec(id="watercolor", name="수채"),
    ImageStyleSpec(id="pixel_art", name="픽셀"),
    ImageStyleSpec(id="deco_cute", name="데포르메"),
)
