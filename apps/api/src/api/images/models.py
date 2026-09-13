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
    # local-image-gen-goal-prompt.md LG-16: 로컬 전환 후 첫 실사용 프리셋.
    BASE = "base"
    # image-refact-goal-prompt.md IR-12/IR-13: 레지스트리엔 있지만 아직 어떤 와이어
    # style에도 매핑되지 않아 `available: false`로 내려간다(image-refact-techspec.md
    # IT-3). 매핑을 켜는 작업은 별도 런(§7-3).
    LINE = "line"  # 극화
    WATER = "water"  # 수채
    REAL = "real"  # 반실사


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


# image-refact-techspec.md IT-1: base의 id는 그대로 두고 표시명만 "기본"→"순정"으로
# 바꾼다(IR-12). 순서가 곧 `GET /images/models`의 응답 순서다(IT-3).
IMAGE_STYLE_PRESETS: tuple[ImageStyleSpec, ...] = (
    ImageStyleSpec(id="base", name="순정"),
    ImageStyleSpec(id="line", name="극화"),
    ImageStyleSpec(id="water", name="수채"),
    ImageStyleSpec(id="real", name="반실사"),
)
