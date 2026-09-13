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


class ImageStylePreset(str, enum.Enum):
    # local-image-gen-goal-prompt.md LG-16: 로컬 전환 후의 유일한 실사용 프리셋.
    BASE = "base"


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


IMAGE_STYLE_PRESETS: tuple[ImageStyleSpec, ...] = (ImageStyleSpec(id="base", name="기본"),)
IMAGE_STYLE_PRESETS_BY_ID: dict[str, ImageStyleSpec] = {s.id: s for s in IMAGE_STYLE_PRESETS}
