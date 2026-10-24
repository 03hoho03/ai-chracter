"""채팅 레인의 단계 표 — 한 턴이 부르는 생성·판정·요약·추출을 단계로 나누고, 단계마다 어느 호출 위치가 부르고 어느 채널을
읽는지 한 행에 적는다.

모델 배정 표(`prompt_routes`)의 단계 축, 그 표의 해석·저장 검사(`chat/prompt_routing.py`), 게시 검증의 판정 채널 표
(`admin/prompts.py`)가 이 표를 읽는다. 잎 모듈로 둔다 — `typing`·`dataclasses` 와 호출 정책 표의 타입만 import 한다.
`chat/prompt_builder.py` 를 import 하지 않는 것은 그 모듈에서 `llm/chat_models.py` → `core/config.py` → `llm/call_policy.py`
로 이어지는 고리가 있어, 나중에 프롬프트 빌더가 채널 이름을 이 표에서 읽게 되면 순환이 되기 때문이다. 그래서 레인 타입도
`PromptLane` 을 가져오지 않고 여기 따로 두며, 두 집합의 부분 관계는 테스트가 본다.

소설·심사 레인은 이 표에 없다. 그 레인의 세트 선택은 모델 배정 표를 따르지 않는다.
"""

from dataclasses import dataclass
from typing import Literal

from api.llm.call_policy import LLMCallSite

# 생성 단계만 호출 위치 이름 그대로이고, 나머지는 채팅 호출 위치에서 `chat_` 를 뗀 이름이다. 모델 배정 표의 `stage` 칸 값이라
# 바꾸면 저장된 행이 이 표 밖 값이 된다.
PromptStage = Literal[
    "chat_generate",
    "stat_judgment",
    "scene_judgment",
    "ending_judgment",
    "situational_image",
    "media_book_image",
    "memory_summary",
    "memory_episode",
    "memory_fact",
]

# 모델 배정 표를 따르는 레인 — 채팅 두 레인뿐이다.
RoutingLane = Literal["story", "character"]

# 생성은 방 모델로 스트리밍하고, 나머지는 모델 설정으로 고른 모델의 구조화 호출이다. 허용하는 (모델, 경로) 쌍이 종류마다 다르다.
StageKind = Literal["generation", "structured"]


@dataclass(frozen=True, kw_only=True)
class StageSpec:
    kind: StageKind
    # 채팅 턴에서 이 단계를 부르는 호출 위치. 행이 없을 때 env 규칙을 이 호출 위치의 설정·배정으로 푼다.
    chat_call_site: LLMCallSite
    # 빌더 미리보기에서 같은 행을 읽는 호출 위치. 미리보기 생성은 모델을 고를 수 없는 호출이라 표를 따르지 않아 넣지 않는다.
    preview_call_site: LLMCallSite | None
    # 이 단계가 읽는 프롬프트 채널. 행이 고른 체인이 이 채널을 다 가져야 한다.
    channels: tuple[str, ...]
    # 자기 행이 없을 때 물려받을 같은 (레인, 방 모델)의 단계. 장면 헤더가 스탯 판정과 같은 모델·경로로 가게 하려고 둔다 — 호출
    # 정책 표에서 장면 헤더 호출이 스탯 판정의 모델 설정과 배정을 함께 쓰는 것과 같은 이유다.
    inherits_from: "PromptStage | None" = None


STAGES: dict[PromptStage, StageSpec] = {
    "chat_generate": StageSpec(
        kind="generation", chat_call_site="chat_generate", preview_call_site=None, channels=("system", "generation")
    ),
    "stat_judgment": StageSpec(
        kind="structured",
        chat_call_site="chat_stat_judgment",
        preview_call_site="preview_stat_judgment",
        channels=("stat_rule_judgment",),
    ),
    "scene_judgment": StageSpec(
        kind="structured",
        chat_call_site="chat_scene_judgment",
        preview_call_site="preview_scene_judgment",
        channels=("scene_judgment",),
        inherits_from="stat_judgment",
    ),
    "ending_judgment": StageSpec(
        kind="structured",
        chat_call_site="chat_ending_judgment",
        preview_call_site="preview_ending_judgment",
        channels=("ending_judgment",),
    ),
    "situational_image": StageSpec(
        kind="structured", chat_call_site="chat_situational_image", preview_call_site=None, channels=("image_judgment",)
    ),
    "media_book_image": StageSpec(
        kind="structured",
        chat_call_site="chat_media_book_image",
        preview_call_site="preview_media_book_image",
        channels=("image_judgment",),
    ),
    "memory_summary": StageSpec(
        kind="structured", chat_call_site="chat_memory_summary", preview_call_site=None, channels=("memory_summary",)
    ),
    "memory_episode": StageSpec(
        kind="structured", chat_call_site="chat_memory_episode", preview_call_site=None, channels=("memory_episode",)
    ),
    "memory_fact": StageSpec(
        kind="structured", chat_call_site="chat_memory_fact", preview_call_site=None, channels=("memory_fact",)
    ),
}

# 레인마다 그 레인의 턴이 부르는 단계. 스탯·장면 헤더·엔딩·미디어 북은 스토리에만, 상황 이미지는 캐릭터에만 있다.
LANE_STAGES: dict[RoutingLane, tuple[PromptStage, ...]] = {
    "story": (
        "chat_generate",
        "stat_judgment",
        "scene_judgment",
        "ending_judgment",
        "media_book_image",
        "memory_summary",
        "memory_episode",
        "memory_fact",
    ),
    "character": ("chat_generate", "situational_image", "memory_summary", "memory_episode", "memory_fact"),
}


def stage_call_sites(stage: PromptStage) -> tuple[LLMCallSite, ...]:
    """그 단계의 행을 읽는 호출 위치 전부(채팅, 그리고 있으면 미리보기)."""
    spec = STAGES[stage]
    if spec.preview_call_site is None:
        return (spec.chat_call_site,)
    return (spec.chat_call_site, spec.preview_call_site)


def stage_channels(lane: RoutingLane, kind: StageKind) -> frozenset[str]:
    """그 레인에서 그 종류의 단계들이 읽는 채널의 합집합."""
    return frozenset(
        channel for stage in LANE_STAGES[lane] if STAGES[stage].kind == kind for channel in STAGES[stage].channels
    )
