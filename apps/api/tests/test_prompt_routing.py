"""모델 배정 표의 해석(`resolve_stage_route`).

빈 표의 기대값(`fixtures/prompt_routes_empty_table_characterization.json`)은 해석 함수가 생기기 전 코드에서 만들었다. 그 코드의
src 를 `sys.path` 맨 앞에 둔 생성 스크립트가, 이미 있던 함수만으로(판정 세트 고르기의 칸별 호출 위치 표와
`configured_call_site_model`, `pick_backend`, `backend_model_id`, `structured_model`) 케이스마다 단계·호출 위치별 "지금 규칙"의
읽을 체인·부를 모델·경로·실제 모델 id 를 적었다. 판정 칸의 읽을 체인은 판정 세트 고르기가 그 칸을 읽는 호출 위치(장면 헤더는 스탯
칸, 미디어 북은 상황 이미지 칸)의 모델이고, 경로는 `resolve_backend` 와 같은 인자로 푼 값이다. 지금 규칙은 레인을 보지 않고 방
모델은 생성 단계에서만 보므로, 판정 칸은 방 모델 "*" 한 줄로 적고 테스트가 레인 둘 × 방 모델 둘을 모두 그 줄과 대조한다.

출력에 영향을 주는 설정(Gemini 모델명들, Claude 모델 id 여섯, 구조화 깊이, 판정·요약 모델 설정 여섯, 호출 위치 배정)은 생성
스크립트와 이 테스트가 같은 리터럴(`_FIXED_SETTINGS`)로 고정한다. env 나 로컬 `.env` 를 읽지 않으므로 로컬과 CI 가 같은 값을
계산한다. 기대값 파일 머리에 생성 때 쓴 고정값과 케이스 목록이 적혀 있어, 이 테스트가 먼저 그것이 자기 것과 같은지 본다. 기대값을
다시 만들어야 한다면 해석 함수가 없는 코드에서 같은 방식으로 만들어야 한다 — 해석 함수로 만들면 대조가 항진명제가 된다.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_routing import (
    ALLOWED_ROUTE_PAIRS,
    PromptRoutes,
    RouteRow,
    RouteRowInput,
    StageRoute,
    parse_route_row,
    resolve_stage_route,
    route_chain_errors,
    route_row_errors,
)
from api.chat.prompt_stages import LANE_STAGES, STAGES, RoutingLane, stage_call_sites
from api.core.config import settings
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.call_policy import CALL_POLICIES, BackendId, LLMCallSite
from api.llm.chat_models import ChatRoomModelId, PromptSetModelId, backend_model_id
from api.llm.client import structured_model

_EXPECTED_PATH = Path(__file__).parent / "fixtures" / "prompt_routes_empty_table_characterization.json"

_FIXED_SETTINGS: dict[str, Any] = {
    "gemini_model_name": "fixture-gemini-base",
    "gemini_stat_judgment_model_name": "fixture-gemini-stat",
    "gemini_ending_judgment_model_name": "fixture-gemini-ending",
    "gemini_image_judgment_model_name": None,
    "gemini_publish_filter_model_name": "fixture-gemini-publish-filter",
    "gemini_novelize_model_name": "fixture-gemini-novelize",
    "bedrock_sonnet_model_id": "fixture-bedrock-sonnet",
    "bedrock_opus_model_id": "fixture-bedrock-opus",
    "bedrock_haiku_model_id": "fixture-bedrock-haiku",
    "anthropic_sonnet_model_id": "fixture-anthropic-sonnet",
    "anthropic_opus_model_id": "fixture-anthropic-opus",
    "anthropic_haiku_model_id": "fixture-anthropic-haiku",
    "anthropic_structured_effort": "low",
    "stat_judgment_model": "gemini",
    "ending_judgment_model": "gemini",
    "image_judgment_model": "gemini",
    "memory_summary_model": "gemini",
    "memory_episode_model": "gemini",
    "memory_fact_model": "gemini",
    "llm_call_site_backends": {},
}

_MODEL_SETTINGS = (
    "stat_judgment_model",
    "ending_judgment_model",
    "image_judgment_model",
    "memory_summary_model",
    "memory_episode_model",
    "memory_fact_model",
)


def _cases() -> list[dict[str, Any]]:
    """기본값 하나, 판정·요약 설정 여섯 × 값 넷 × 배정 셋(없음·그 설정을 쓰는 호출 위치 전부 anthropic·전부 bedrock), 그리고
    호출 위치마다 배정이 갈리는 케이스(스탯만 배정해 장면 헤더가 물려받음, 장면 헤더만 다른 경로, 미디어 북만 배정)와 생성 배정 둘."""
    cases: list[dict[str, Any]] = [{"name": "defaults", "settings": {}}]
    for setting in _MODEL_SETTINGS:
        sites = [cs for cs, policy in CALL_POLICIES.items() if policy.model_setting == setting]
        for value in ("gemini", "sonnet", "opus", "haiku"):
            for assign in (None, "anthropic", "bedrock"):
                overrides: dict[str, Any] = {setting: value}
                if assign is not None:
                    overrides["llm_call_site_backends"] = dict.fromkeys(sites, assign)
                cases.append({"name": f"{setting}={value}/{assign or 'unassigned'}", "settings": overrides})
    stat_on_anthropic = {"chat_stat_judgment": "anthropic", "preview_stat_judgment": "anthropic"}
    cases.append(
        {
            "name": "stat-haiku/stat-call-sites-on-anthropic",
            "settings": {"stat_judgment_model": "haiku", "llm_call_site_backends": stat_on_anthropic},
        }
    )
    cases.append(
        {
            "name": "stat-haiku/stat-on-anthropic-scene-on-bedrock",
            "settings": {
                "stat_judgment_model": "haiku",
                "llm_call_site_backends": {
                    **stat_on_anthropic,
                    "chat_scene_judgment": "bedrock",
                    "preview_scene_judgment": "bedrock",
                },
            },
        }
    )
    cases.append(
        {
            "name": "image-haiku/media-book-only-on-anthropic",
            "settings": {
                "image_judgment_model": "haiku",
                "llm_call_site_backends": {
                    "chat_media_book_image": "anthropic",
                    "preview_media_book_image": "anthropic",
                },
            },
        }
    )
    for assign in ("anthropic", "bedrock"):
        cases.append(
            {"name": f"generate-on-{assign}", "settings": {"llm_call_site_backends": {"chat_generate": assign}}}
        )
    return cases


@pytest.fixture
def fixed_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    for name, value in _FIXED_SETTINGS.items():
        monkeypatch.setattr(settings, name, value)
    yield monkeypatch


def _model_id(call_site: LLMCallSite, backend: BackendId, model: PromptSetModelId) -> str:
    if backend == "gemini":
        return structured_model(call_site, settings.gemini_model_name)
    return backend_model_id(backend, model)


def _resolve(
    routes: PromptRoutes,
    lane: RoutingLane,
    room_model: ChatRoomModelId,
    stage: str,
    call_site: LLMCallSite | None = None,
) -> StageRoute:
    assert stage in STAGES
    return resolve_stage_route(routes, lane=lane, room_model=room_model, stage=stage, call_site=call_site)


def test_an_empty_table_resolves_every_cell_the_way_the_env_rules_do_today(fixed_settings: pytest.MonkeyPatch) -> None:
    expected = json.loads(_EXPECTED_PATH.read_text())
    assert expected["fixedSettings"] == _FIXED_SETTINGS
    assert expected["cases"] == _cases()
    by_key = {(row[0], row[1], row[2], row[3]): row[4:] for row in expected["rows"]}

    compared = 0
    for case in expected["cases"]:
        with fixed_settings.context() as patch:
            for name, value in case["settings"].items():
                patch.setattr(settings, name, value)
            for lane in get_args(RoutingLane):
                for room_model in get_args(ChatRoomModelId):
                    for stage, spec in STAGES.items():
                        room_key = room_model if spec.kind == "generation" else "*"
                        for call_site in stage_call_sites(stage):
                            route = _resolve(PromptRoutes.empty(), lane, room_model, stage, call_site)
                            actual = [
                                route.chain_model,
                                route.call_model,
                                route.backend,
                                _model_id(call_site, route.backend, route.call_model),
                            ]
                            assert actual == by_key[(case["name"], room_key, stage, call_site)], (
                                case["name"],
                                lane,
                                room_model,
                                call_site,
                            )
                            assert route.skipped is None
                            compared += 1
    assert compared == len(expected["cases"]) * 2 * 2 * 13


def test_an_empty_table_names_where_each_cell_came_from(fixed_settings: pytest.MonkeyPatch) -> None:
    fixed_settings.setattr(settings, "memory_fact_model", "haiku")

    generation = _resolve(PromptRoutes.empty(), "story", "opus", "chat_generate")
    fact = _resolve(PromptRoutes.empty(), "character", "gemini", "memory_fact")

    assert (generation.source, generation.source_detail) == ("room", None)
    assert (generation.chain_model, generation.call_model) == ("opus", "opus")
    assert (fact.source, fact.source_detail) == ("env", "MEMORY_FACT_MODEL")
    assert (fact.chain_model, fact.call_model, fact.backend) == ("haiku", "haiku", "bedrock")


def _row(
    stage: str,
    *,
    lane: RoutingLane = "story",
    room_model: ChatRoomModelId = "opus",
    chain_model: PromptSetModelId | None = "haiku",
    call_model: PromptSetModelId = "haiku",
    backend: BackendId = "anthropic",
) -> RouteRow:
    assert stage in STAGES
    return RouteRow(
        lane=lane,
        room_model=room_model,
        stage=stage,
        chain_model=chain_model,
        call_model=call_model,
        backend=backend,
    )


# 판정 모델이 Claude 이고 그 호출 위치가 직결로 배정된 env — 직결 행을 저장할 수 있는 운영 상태다.
_JUDGMENTS_ON_ANTHROPIC: dict[str, Any] = {
    "stat_judgment_model": "sonnet",
    "ending_judgment_model": "sonnet",
    "image_judgment_model": "sonnet",
    "memory_fact_model": "sonnet",
    "llm_call_site_backends": {
        "chat_stat_judgment": "anthropic",
        "preview_stat_judgment": "anthropic",
        "chat_ending_judgment": "anthropic",
        "preview_ending_judgment": "anthropic",
        "chat_situational_image": "anthropic",
        "chat_media_book_image": "anthropic",
        "preview_media_book_image": "anthropic",
        "chat_memory_fact": "anthropic",
        "chat_generate": "anthropic",
    },
}


@pytest.fixture
def judgments_on_anthropic(fixed_settings: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name, value in _JUDGMENTS_ON_ANTHROPIC.items():
        fixed_settings.setattr(settings, name, value)
    return fixed_settings


def test_a_row_overrides_env_for_its_cell_only(judgments_on_anthropic: pytest.MonkeyPatch) -> None:
    routes = PromptRoutes.from_rows([_row("stat_judgment", chain_model="opus", call_model="haiku")])

    own = _resolve(routes, "story", "opus", "stat_judgment")
    other_room = _resolve(routes, "story", "gemini", "stat_judgment")
    other_lane = _resolve(routes, "character", "opus", "memory_fact")

    assert (own.chain_model, own.call_model, own.backend, own.source) == ("opus", "haiku", "anthropic", "row")
    assert own.skipped is None
    assert (other_room.chain_model, other_room.call_model, other_room.source) == ("sonnet", "sonnet", "env")
    assert (other_lane.chain_model, other_lane.call_model, other_lane.source) == ("sonnet", "sonnet", "env")


def test_a_generation_row_reads_the_room_chain_and_takes_only_its_backend(
    judgments_on_anthropic: pytest.MonkeyPatch,
) -> None:
    routes = PromptRoutes.from_rows([_row("chat_generate", chain_model=None, call_model="opus")])

    route = _resolve(routes, "story", "opus", "chat_generate")

    assert (route.chain_model, route.call_model, route.backend, route.source) == ("opus", "opus", "anthropic", "row")


def test_the_scene_header_inherits_the_stat_row_when_it_has_none(judgments_on_anthropic: pytest.MonkeyPatch) -> None:
    routes = PromptRoutes.from_rows([_row("stat_judgment", chain_model="opus", call_model="haiku")])

    for call_site in ("chat_scene_judgment", "preview_scene_judgment"):
        route = _resolve(routes, "story", "opus", "scene_judgment", call_site)
        assert (route.chain_model, route.call_model, route.backend) == ("opus", "haiku", "anthropic")
        assert (route.source, route.source_detail) == ("inherited", "stat_judgment")


def test_a_scene_header_row_beats_the_inherited_stat_row(judgments_on_anthropic: pytest.MonkeyPatch) -> None:
    routes = PromptRoutes.from_rows(
        [
            _row("stat_judgment", chain_model="opus", call_model="haiku"),
            _row("scene_judgment", chain_model="sonnet", call_model="sonnet"),
        ]
    )

    route = _resolve(routes, "story", "opus", "scene_judgment")

    assert (route.chain_model, route.call_model, route.source) == ("sonnet", "sonnet", "row")


def test_the_media_book_cell_falls_back_to_env_even_when_other_image_or_stat_rows_exist(
    judgments_on_anthropic: pytest.MonkeyPatch,
) -> None:
    routes = PromptRoutes.from_rows(
        [
            _row("stat_judgment", chain_model="opus", call_model="haiku"),
            _row("situational_image", lane="character", chain_model="opus", call_model="haiku"),
        ]
    )

    route = _resolve(routes, "story", "opus", "media_book_image")

    assert (route.chain_model, route.call_model, route.source, route.source_detail) == (
        "sonnet",
        "sonnet",
        "env",
        "IMAGE_JUDGMENT_MODEL",
    )


def test_a_cell_outside_its_lane_always_resolves_from_env(judgments_on_anthropic: pytest.MonkeyPatch) -> None:
    routes = PromptRoutes.from_rows([_row("stat_judgment", room_model="opus", chain_model="opus", call_model="haiku")])

    route = _resolve(routes, "character", "opus", "stat_judgment")

    assert (route.chain_model, route.call_model, route.source) == ("sonnet", "sonnet", "env")


def test_a_call_site_of_another_stage_is_a_caller_bug(fixed_settings: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="chat_ending_judgment"):
        _resolve(PromptRoutes.empty(), "story", "opus", "stat_judgment", "chat_ending_judgment")


def test_a_table_with_two_rows_for_one_cell_is_refused() -> None:
    with pytest.raises(ValueError, match="stat_judgment"):
        PromptRoutes.from_rows([_row("stat_judgment"), _row("stat_judgment", call_model="sonnet")])


# 행이 저장된 뒤 env 가 바뀌어 행의 경로가 더는 실제 경로가 아니거나 깊이 상한에 걸리면, 해석은 그 행을 건너뛰고 env 규칙으로
# 간다. 기동은 멈추지 않고 DB 를 읽지 않는다 — 판단은 행과 설정만 보는 순수 계산이다.


def test_a_row_whose_backend_no_longer_matches_the_env_assignment_falls_back_to_env_and_says_why(
    judgments_on_anthropic: pytest.MonkeyPatch,
) -> None:
    judgments_on_anthropic.setattr(
        settings,
        "llm_call_site_backends",
        {**_JUDGMENTS_ON_ANTHROPIC["llm_call_site_backends"], "preview_ending_judgment": "bedrock"},
    )
    routes = PromptRoutes.from_rows([_row("ending_judgment", chain_model="opus", call_model="haiku")])

    for call_site in ("chat_ending_judgment", "preview_ending_judgment"):
        route = _resolve(routes, "story", "opus", "ending_judgment", call_site)
        assert (route.chain_model, route.call_model, route.source) == ("sonnet", "sonnet", "env"), call_site
        assert route.skipped is not None
        assert (route.skipped.stage, route.skipped.reason) == ("ending_judgment", "backend-mismatch")
        assert "preview_ending_judgment" in route.skipped.message


def test_a_row_whose_backend_still_matches_the_env_assignment_is_applied(
    judgments_on_anthropic: pytest.MonkeyPatch,
) -> None:
    routes = PromptRoutes.from_rows([_row("ending_judgment", chain_model="opus", call_model="haiku")])

    route = _resolve(routes, "story", "opus", "ending_judgment", "preview_ending_judgment")

    assert (route.chain_model, route.call_model, route.backend, route.source) == ("opus", "haiku", "anthropic", "row")
    assert route.skipped is None


def test_a_row_over_the_structured_effort_ceiling_falls_back_to_env(judgments_on_anthropic: pytest.MonkeyPatch) -> None:
    judgments_on_anthropic.setattr(settings, "anthropic_haiku_model_id", "claude-haiku-5-5")
    judgments_on_anthropic.setattr(settings, "anthropic_structured_effort", "xhigh")
    routes = PromptRoutes.from_rows(
        [
            _row("memory_fact", lane="character", chain_model="haiku", call_model="haiku"),
            _row("memory_fact", lane="story", chain_model="opus", call_model="opus"),
        ]
    )

    over = _resolve(routes, "character", "opus", "memory_fact")
    under = _resolve(routes, "story", "opus", "memory_fact")

    assert (over.call_model, over.source) == ("sonnet", "env")
    assert over.skipped is not None
    assert over.skipped.reason == "structured-effort"
    assert "ANTHROPIC_STRUCTURED_EFFORT=xhigh" in over.skipped.message
    assert (under.call_model, under.source, under.skipped) == ("opus", "row", None)


def test_a_row_outside_the_allowed_pairs_is_never_applied_even_when_its_path_is_real(
    fixed_settings: pytest.MonkeyPatch,
) -> None:
    """배정이 없으면 Claude 판정은 Bedrock 으로 가 경로 대조는 맞는다. 그래도 허용 목록 밖 경로라 쓰지 않는다."""
    fixed_settings.setattr(settings, "stat_judgment_model", "sonnet")
    routes = PromptRoutes.from_rows(
        [_row("stat_judgment", chain_model="sonnet", call_model="sonnet", backend="bedrock")]
    )

    route = _resolve(routes, "story", "opus", "stat_judgment")

    assert route.source == "env"
    assert route.skipped is not None
    assert route.skipped.reason == "pair-not-allowed"
    assert ("sonnet", "bedrock") not in ALLOWED_ROUTE_PAIRS["structured"]


def test_an_inherited_stat_row_whose_scene_header_path_drifted_is_skipped_for_both_stages(
    judgments_on_anthropic: pytest.MonkeyPatch,
) -> None:
    """장면 헤더가 물려받은 스탯 행이 장면 헤더 호출 위치에서 다른 경로로 가게 되면, 장면 헤더만 env 로 돌리면 둘이 다른 모델로
    간다. 그래서 그 행을 읽는 두 단계를 함께 env 로 돌린다."""
    judgments_on_anthropic.setattr(
        settings,
        "llm_call_site_backends",
        {**_JUDGMENTS_ON_ANTHROPIC["llm_call_site_backends"], "chat_scene_judgment": "bedrock"},
    )
    routes = PromptRoutes.from_rows([_row("stat_judgment", chain_model="opus", call_model="haiku")])

    stat = _resolve(routes, "story", "opus", "stat_judgment")
    scene = _resolve(routes, "story", "opus", "scene_judgment", "preview_scene_judgment")

    for route in (stat, scene):
        assert (route.call_model, route.source) == ("sonnet", "env")
        assert route.skipped is not None
        assert (route.skipped.stage, route.skipped.reason) == ("stat_judgment", "backend-mismatch")
        assert "chat_scene_judgment" in route.skipped.message


def test_a_generation_row_whose_backend_drifted_falls_back_to_the_room_rule(fixed_settings: pytest.MonkeyPatch) -> None:
    routes = PromptRoutes.from_rows([_row("chat_generate", chain_model=None, call_model="opus")])

    route = _resolve(routes, "story", "opus", "chat_generate")

    assert (route.call_model, route.backend, route.source) == ("opus", "bedrock", "room")
    assert route.skipped is not None
    assert route.skipped.reason == "backend-mismatch"


def test_every_lane_stage_resolves_on_an_empty_table_without_error(fixed_settings: pytest.MonkeyPatch) -> None:
    for lane, stages in LANE_STAGES.items():
        for stage in stages:
            assert _resolve(PromptRoutes.empty(), lane, "gemini", stage).skipped is None


# --- 어드민 저장 검사 ---------------------------------------------------------------------------------------------------


@pytest.fixture
def save_env(judgments_on_anthropic: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    judgments_on_anthropic.setattr(settings, "anthropic_direct_api_key", "sk-test")
    for name in ("bedrock_access_key_id", "bedrock_secret_access_key", "bedrock_region"):
        judgments_on_anthropic.setattr(settings, name, "")
    return judgments_on_anthropic


def _input(
    stage: str,
    *,
    lane: str = "story",
    room_model: str = "opus",
    chain_model: str | None = "haiku",
    call_model: str = "haiku",
    backend: str = "anthropic",
) -> RouteRowInput:
    return RouteRowInput(
        lane=lane, room_model=room_model, stage=stage, chain_model=chain_model, call_model=call_model, backend=backend
    )


def _rules(rows: list[RouteRowInput]) -> list[tuple[int, str]]:
    return [(error.index, error.rule) for error in route_row_errors(rows)]


def test_every_allowed_structured_pair_saves_when_the_env_routes_it_there(save_env: pytest.MonkeyPatch) -> None:
    rows = [
        _input("stat_judgment", chain_model="gemini", call_model="gemini", backend="gemini"),
        _input("ending_judgment", chain_model="opus", call_model="haiku"),
        _input("media_book_image", chain_model="sonnet", call_model="sonnet"),
        _input("memory_fact", lane="character", chain_model="opus", call_model="opus"),
        _input("chat_generate", chain_model=None, call_model="opus"),
        _input("chat_generate", room_model="gemini", chain_model=None, call_model="gemini", backend="gemini"),
    ]

    assert route_row_errors(rows) == []


@pytest.mark.parametrize(
    ("row", "rule"),
    [
        pytest.param(_input("stat_judgment", lane="character"), "unknown-stage", id="stat-is-not-a-character-stage"),
        pytest.param(_input("situational_image"), "unknown-stage", id="situational-is-not-a-story-stage"),
        pytest.param(_input("memory_fact", lane="novel"), "unknown-stage", id="novel-lane"),
        pytest.param(_input("memory_fact", room_model="sonnet"), "unknown-stage", id="sonnet-room"),
        pytest.param(
            _input("chat_generate", chain_model="opus", call_model="opus"), "generation-chain", id="gen-chain"
        ),
        pytest.param(_input("memory_fact", chain_model=None), "generation-chain", id="judgment-without-chain"),
        pytest.param(_input("memory_fact", chain_model="flash"), "generation-chain", id="chain-off-the-model-axis"),
        pytest.param(
            _input("chat_generate", chain_model=None, call_model="haiku"), "generation-call-model", id="gen-haiku"
        ),
        pytest.param(
            _input("chat_generate", chain_model=None, call_model="opus", backend="bedrock"),
            "pair-not-allowed",
            id="gen-opus-on-bedrock",
        ),
        pytest.param(
            _input("chat_generate", room_model="gemini", chain_model=None, call_model="gemini", backend="anthropic"),
            "pair-not-allowed",
            id="gen-gemini-on-anthropic",
        ),
        pytest.param(_input("memory_fact", call_model="gpt"), "pair-not-allowed", id="call-model-off-the-axis"),
    ],
)
def test_a_row_breaking_a_shape_rule_is_refused_by_that_rule(
    save_env: pytest.MonkeyPatch, row: RouteRowInput, rule: str
) -> None:
    assert _rules([row]) == [(0, rule)]


def test_a_bedrock_pair_is_refused_even_when_assigned_and_credentialed(save_env: pytest.MonkeyPatch) -> None:
    """처리방침의 수탁자 밖 경로라 env 가 그 경로를 받쳐도 표에는 둘 수 없다."""
    save_env.setattr(settings, "llm_call_site_backends", {"chat_memory_fact": "bedrock"})
    save_env.setattr(settings, "bedrock_access_key_id", "AKIATEST")
    save_env.setattr(settings, "bedrock_secret_access_key", "secret")
    save_env.setattr(settings, "bedrock_region", "ap-northeast-2")

    assert _rules([_input("memory_fact", chain_model="sonnet", call_model="sonnet", backend="bedrock")]) == [
        (0, "pair-not-allowed")
    ]


def test_a_second_row_for_the_same_cell_is_refused(save_env: pytest.MonkeyPatch) -> None:
    rows = [_input("ending_judgment"), _input("ending_judgment", call_model="sonnet", chain_model="sonnet")]

    assert _rules(rows) == [(1, "duplicate-row")]


def test_a_row_assigned_for_chat_but_not_for_preview_is_a_backend_mismatch(save_env: pytest.MonkeyPatch) -> None:
    assignments = dict(_JUDGMENTS_ON_ANTHROPIC["llm_call_site_backends"])
    del assignments["preview_ending_judgment"]
    save_env.setattr(settings, "llm_call_site_backends", assignments)

    errors = route_row_errors([_input("ending_judgment")])

    assert [(error.index, error.rule) for error in errors] == [(0, "backend-mismatch")]
    assert "preview_ending_judgment" in errors[0].message


def test_a_stat_row_inherited_by_a_scene_header_on_another_path_is_a_backend_mismatch(
    save_env: pytest.MonkeyPatch,
) -> None:
    """장면 헤더 호출 위치는 자기 env 배정을 먼저 본다. 장면 헤더 행 없이 스탯 행만 저장하면 장면 헤더가 그 행을 물려받으므로,
    장면 헤더 호출 위치에서도 같은 경로로 가야 한다."""
    save_env.setattr(
        settings,
        "llm_call_site_backends",
        {**_JUDGMENTS_ON_ANTHROPIC["llm_call_site_backends"], "chat_scene_judgment": "bedrock"},
    )
    stat_row = _input("stat_judgment", chain_model="sonnet", call_model="sonnet")

    alone = route_row_errors([stat_row])
    with_scene_row = route_row_errors(
        [stat_row, _input("scene_judgment", chain_model="gemini", call_model="gemini", backend="gemini")]
    )

    assert [(error.index, error.rule) for error in alone] == [(0, "backend-mismatch")]
    assert "chat_scene_judgment" in alone[0].message
    assert with_scene_row == []


def test_a_direct_route_without_its_key_is_refused(save_env: pytest.MonkeyPatch) -> None:
    save_env.setattr(settings, "anthropic_direct_api_key", " ")

    errors = route_row_errors([_input("memory_fact")])

    assert [(error.index, error.rule) for error in errors] == [(0, "missing-credentials")]
    assert "ANTHROPIC_DIRECT_API_KEY" in errors[0].message


def test_a_haiku_5_judgment_over_the_effort_ceiling_is_refused_but_haiku_4_is_not(save_env: pytest.MonkeyPatch) -> None:
    save_env.setattr(settings, "anthropic_structured_effort", "xhigh")
    save_env.setattr(settings, "anthropic_haiku_model_id", "claude-haiku-5-5")
    over = route_row_errors([_input("memory_fact")])
    save_env.setattr(settings, "anthropic_haiku_model_id", "claude-haiku-4-5")
    under = route_row_errors([_input("memory_fact")])

    assert [(error.index, error.rule) for error in over] == [(0, "structured-effort")]
    assert "ANTHROPIC_STRUCTURED_EFFORT=xhigh" in over[0].message
    assert under == []


def test_each_row_reports_only_its_first_broken_rule(save_env: pytest.MonkeyPatch) -> None:
    save_env.setattr(settings, "anthropic_direct_api_key", "")

    rows = [
        _input("memory_fact", call_model="sonnet", chain_model="sonnet", backend="bedrock"),
        _input("memory_fact", lane="character"),
        _input("memory_episode", chain_model=None),
    ]

    assert _rules(rows) == [(0, "pair-not-allowed"), (1, "missing-credentials"), (2, "generation-chain")]


def test_a_parsed_row_keeps_its_values_and_an_out_of_range_row_is_none() -> None:
    assert parse_route_row(_input("chat_generate", chain_model=None, call_model="opus")) == _row(
        "chat_generate", chain_model=None, call_model="opus"
    )
    assert parse_route_row(_input("memory_fact", lane="character", chain_model="opus")) == _row(
        "memory_fact", lane="character", chain_model="opus"
    )
    assert parse_route_row(_input("stat_judgment", lane="character")) is None
    assert parse_route_row(_input("memory_fact", backend="openai")) is None
    assert parse_route_row(_input("memory_fact", chain_model=None)) is None
    assert parse_route_row(_input("chat_generate", chain_model="opus", call_model="opus")) is None


async def _publish_haiku_story_set_with(db_session: AsyncSession, channels: list[str]) -> None:
    """이미 있는 체인보다 늦은 게시 시각으로, 주어진 채널만 가진 (story, haiku) 세트를 게시한다."""
    prompt_set = PromptSet(
        status="published",
        lane="story",
        model="haiku",
        user_label="사용자",
        story_assistant_label="서술자",
        story_example_label="예시",
        character_assistant_label="캐릭터",
        published_at=datetime(2099, 1, 1, tzinfo=UTC),
    )
    db_session.add(prompt_set)
    await db_session.flush()
    for order, channel in enumerate(channels):
        db_session.add(
            PromptSection(
                prompt_set_id=prompt_set.id,
                channel=channel,
                scope="both",
                slot="instruction",
                variant="",
                body="합성 문안",
                conditional=False,
                order=order,
            )
        )
    await db_session.flush()


async def test_a_chain_without_a_channel_its_stage_reads_is_refused(db_session: AsyncSession) -> None:
    await _publish_haiku_story_set_with(db_session, ["stat_rule_judgment", "memory_fact"])
    rows = [
        _row("stat_judgment", chain_model="haiku"),
        _row("scene_judgment", chain_model="haiku"),
        _row("memory_fact", chain_model="haiku"),
    ]

    errors = await route_chain_errors(db_session, rows)

    assert [(error.index, error.rule) for error in errors] == [(1, "chain-missing-channel")]
    assert "scene_judgment" in errors[0].message


async def test_a_chain_with_no_published_set_is_refused(db_session: AsyncSession) -> None:
    await db_session.execute(
        update(PromptSet).where(PromptSet.lane == "character", PromptSet.model == "sonnet").values(status="archived")
    )
    rows = [
        _row("memory_fact", lane="character", chain_model="sonnet"),
        _row("chat_generate", lane="character", room_model="gemini", chain_model=None, call_model="gemini"),
    ]

    errors = await route_chain_errors(db_session, rows)

    assert [(error.index, error.rule) for error in errors] == [(0, "chain-not-published")]
