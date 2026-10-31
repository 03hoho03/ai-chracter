"""채팅 단계 표와, 그 표에서 나오는 게시 검증의 판정 채널 표.

판정 채널 표는 게시 검증이 Claude·판정 전용 체인에 어떤 채널을 요구할지 정한다. 값이 하나라도 바뀌면 그 체인 게시가
"누락"이나 "남는 채널"로 막히거나, 판정이 읽을 문안 없이 게시된다. 그래서 단계 표에서 도출하더라도 지금 값을 리터럴로 묶어 둔다."""

from typing import get_args

from api.admin.prompts import _EXPECTED_SLOTS_BY_LANE, _JUDGMENT_CHANNELS_BY_LANE
from api.chat.prompt_builder import PromptLane
from api.chat.prompt_stages import (
    LANE_STAGES,
    STAGES,
    ChatRoutingLane,
    PromptStage,
    RoutingLane,
    stage_call_sites,
    stage_channels,
    stage_room_models,
)
from api.llm.call_policy import CALL_POLICIES
from api.llm.chat_models import CHAT_MODELS_BY_ID, ChatModelId, ChatRoomModelId


def test_publish_validation_judgment_channels_are_derived_without_changing_them() -> None:
    assert _JUDGMENT_CHANNELS_BY_LANE == {
        "story": frozenset(
            {
                "stat_rule_judgment",
                "scene_judgment",
                "ending_judgment",
                "image_judgment",
                "memory_summary",
                "memory_episode",
                "memory_fact",
                "memory_impression",
            }
        ),
        "character": frozenset(
            {"image_judgment", "memory_summary", "memory_episode", "memory_fact", "memory_impression"}
        ),
        "publish_filter": frozenset(),
        "novel": frozenset(),
        "novel_screen": frozenset(),
    }


def test_impression_channel_is_published_with_judgment_chains_but_is_not_a_routed_stage() -> None:
    """인상 생성은 모델 배정 표 밖에 둔다. 단계 표에서 도출한 채널에는 없고, 게시 검증 표에만 따로 합쳐진다."""
    for lane in ("story", "character"):
        assert "memory_impression" not in stage_channels(lane, "structured")
        assert "memory_impression" in _JUDGMENT_CHANNELS_BY_LANE[lane]


def test_routing_lanes_are_chat_lanes_and_every_stage_belongs_to_some_lane() -> None:
    """레인 타입을 프롬프트 빌더에서 가져오지 않고 따로 둔 대가로, 두 집합이 어긋나지 않는지 여기서 본다."""
    assert set(get_args(RoutingLane)) <= set(get_args(PromptLane))
    assert set(LANE_STAGES) == set(get_args(RoutingLane))
    assert set(STAGES) == set(get_args(PromptStage))
    assert (len(LANE_STAGES["story"]), len(LANE_STAGES["character"])) == (8, 5)
    assert {stage for stages in LANE_STAGES.values() for stage in stages} == set(get_args(PromptStage))
    assert "stat_judgment" not in LANE_STAGES["character"]
    assert "situational_image" not in LANE_STAGES["story"]


def test_every_stage_channel_is_a_channel_that_the_lane_gemini_chain_carries() -> None:
    """채널 이름에 오타가 있으면 저장 검사가 모든 체인을 "채널 빠짐"으로 거부한다. 게시 검증이 Gemini 체인에 요구하는 채널
    집합이 그 레인의 채널 전부다."""
    for lane, stages in LANE_STAGES.items():
        for stage in stages:
            assert set(STAGES[stage].channels) <= set(_EXPECTED_SLOTS_BY_LANE[lane]), (lane, stage)


def test_stages_that_share_a_chain_today_share_one_model_setting() -> None:
    """행이 없을 때 해석 함수는 단계 자기 호출 위치의 모델 설정으로 체인을 고르고, 지금 판정 세트 고르기는 장면 헤더를 스탯
    칸으로, 미디어 북을 상황 이미지 칸으로 읽는다. 둘이 같은 체인을 내는 근거는 같은 설정을 쓴다는 것뿐이라 그 전제를 묶는다."""
    assert CALL_POLICIES["chat_scene_judgment"].model_setting == CALL_POLICIES["chat_stat_judgment"].model_setting
    assert CALL_POLICIES["chat_media_book_image"].model_setting == CALL_POLICIES["chat_situational_image"].model_setting


def test_a_preview_call_site_reads_the_same_model_setting_as_its_chat_call_site() -> None:
    """미리보기 호출 위치는 채팅과 같은 행을 읽는다. 모델 설정이 다르면 행이 없을 때 둘이 다른 체인을 읽는다."""
    chat_stages = {stage for lane in get_args(ChatRoutingLane) for stage in LANE_STAGES[lane]}
    for stage, spec in STAGES.items():
        if stage not in chat_stages:
            continue
        chat_policy = CALL_POLICIES[spec.chat_call_site]
        assert stage_call_sites(stage)[0] == spec.chat_call_site
        if spec.kind == "generation":
            assert chat_policy.model_selectable, stage
            assert spec.preview_call_site is None
            continue
        assert chat_policy.model_setting is not None, stage
        if spec.preview_call_site is not None:
            assert stage_call_sites(stage) == (spec.chat_call_site, spec.preview_call_site)
            assert CALL_POLICIES[spec.preview_call_site].model_setting == chat_policy.model_setting, stage


def test_stage_channels_split_generation_from_the_structured_stages() -> None:
    assert stage_channels("story", "generation") == frozenset({"system", "generation"})
    assert stage_channels("character", "generation") == frozenset({"system", "generation"})
    assert stage_channels("character", "structured") == frozenset(
        {"image_judgment", "memory_summary", "memory_episode", "memory_fact"}
    )


def test_the_novel_lane_has_seven_stages_and_the_job_model_leads_three_of_them() -> None:
    """화 생성·구성안 둘은 작업 모델로 쓰고, 문단 수정·여러 문단 수정·재검사·경계 제안은 작업 모델과 무관한 구조화 호출이다. 단계가
    빠지거나 호출 위치가 틀리면 그 소설 호출의 행이 다른 호출 위치의 경로로 검사된다."""
    assert set(get_args(ChatRoutingLane)) < set(get_args(RoutingLane))
    assert "novel" in get_args(RoutingLane)
    novel = LANE_STAGES["novel"]
    assert {stage: (STAGES[stage].kind, stage_call_sites(stage), STAGES[stage].channels) for stage in novel} == {
        "novel_chapter": ("generation", ("novelize_chapter",), ("novelize_chapter",)),
        "novel_outline": ("generation", ("novelize_outline",), ("novelize_outline",)),
        "novel_episode_outline": ("generation", ("novelize_episode_outline",), ("novelize_episode_outline",)),
        "novel_revise": ("structured", ("novelize_revise",), ("novelize_revise",)),
        "novel_revise_blocks": ("structured", ("novelize_revise",), ("novelize_revise_blocks",)),
        "novel_recheck": ("structured", ("novelize_revise_recheck",), ("novelize_revise_recheck",)),
        "novel_boundary": ("structured", ("novelize_boundary",), ("novelize_boundary",)),
    }
    assert not set(novel) & {stage for lane in get_args(ChatRoutingLane) for stage in LANE_STAGES[lane]}


def test_each_cell_axis_follows_the_lane_and_the_stage() -> None:
    """채팅 칸은 방에서 고를 수 있는 모델, 소설 생성 칸은 작업 모델(소설에서 고를 수 있는 모델 — 채팅 전용 Haiku 글쓰기는 없다), 소설 구조화 칸은 작업 모델과 무관한 표지 `any` 하나다. 축이
    넓으면 아무도 읽지 않는 칸에 행이 저장되고, 좁으면 그 작업 모델의 칸을 저장할 수 없다."""
    for lane in get_args(ChatRoutingLane):
        for stage in LANE_STAGES[lane]:
            assert stage_room_models(lane, stage) == get_args(ChatRoomModelId), (lane, stage)
    for stage in LANE_STAGES["novel"]:
        novel_models = tuple(model for model in get_args(ChatModelId) if CHAT_MODELS_BY_ID[model].novel_selectable)
        expected = novel_models if STAGES[stage].kind == "generation" else ("any",)
        assert stage_room_models("novel", stage) == expected, stage


def test_a_novel_generation_call_site_takes_the_job_model_and_a_structured_one_has_no_model_setting() -> None:
    """빈 표에서 생성 칸은 작업 모델로, 구조화 칸은 그 호출 위치의 모델 설정(없으면 기본 모델)으로 풀린다. 생성 호출이 모델을
    고를 수 없거나 구조화 호출에 모델 설정이 생기면 그 전제가 바뀐다."""
    for stage in LANE_STAGES["novel"]:
        policy = CALL_POLICIES[STAGES[stage].chat_call_site]
        assert STAGES[stage].preview_call_site is None, stage
        if STAGES[stage].kind == "generation":
            assert policy.model_selectable, stage
        else:
            assert not policy.model_selectable, stage
            assert policy.model_setting is None, stage
