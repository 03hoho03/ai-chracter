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

소설 단계의 빈 표 기대값(`fixtures/prompt_routes_novel_empty_table_characterization.json`)은 따로 둔다. 해석 함수가 소설 레인을
풀기 전 커밋에서 `PROMPT_ROUTES_NOVEL_GOLDEN_WRITE=1` 로 이 파일의 기록 테스트를 돌려 만든다. 기록은 해석 함수를 부르지 않고, 소설
호출이 지금 실제로 가는 길을 그 길을 정하는 함수들(공급자 구현을 고르는 라우터와 같은 인자의 `pick_backend`·
`structured_call_model`·`configured_call_site_model`, 소설 문안 체인의 기본 인자)로 적는다. 화 생성·구성안 두 단계는 작업 모델마다,
작업 모델과 무관한 문단 수정·여러 문단 수정·재검사·경계 제안은 작업 모델 셋이 모두 같은 값을 내는지 확인한 뒤 "*" 한 줄로 적는다.
기대값이 다르면 파일을 고치지 말고 멈춘다 — 해석 함수가 소설 레인을 푸는 코드로 다시 만들면 대조가 항진명제가 된다.
"""

import inspect
import json
import os
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
from api.chat.prompt_stages import (
    LANE_STAGES,
    STAGES,
    ChatRoutingLane,
    RouteRoomModel,
    RoutingLane,
    stage_call_sites,
    stage_room_models,
)
from api.core.config import Settings, settings
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.backends import pick_backend
from api.llm.call_policy import CALL_POLICIES, BackendId, LLMCallSite
from api.llm.chat_models import (
    ChatModelId,
    PromptSetModelId,
    backend_model_id,
    configured_call_site_model,
    structured_call_model,
)
from api.llm.client import structured_model
from api.novelize.inputs import load_novel_prompt_source
from factories import load_production_env

_EXPECTED_PATH = Path(__file__).parent / "fixtures" / "prompt_routes_empty_table_characterization.json"
_NOVEL_EXPECTED_PATH = Path(__file__).parent / "fixtures" / "prompt_routes_novel_empty_table_characterization.json"
_NOVEL_WRITE_SWITCH = "PROMPT_ROUTES_NOVEL_GOLDEN_WRITE"

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


# 소설 단계 → 그 단계를 부르는 호출 위치. 문단 수정과 여러 문단 수정은 같은 호출 위치를 쓰고 읽는 채널만 다르다. 기록 때 코드에는
# 이 단계 이름이 없어 여기 적어 두고, 대조 테스트가 해석 쪽 단계 표와 같은지 본다.
_NOVEL_STAGE_CALL_SITES: dict[str, LLMCallSite] = {
    "novel_chapter": "novelize_chapter",
    "novel_outline": "novelize_outline",
    "novel_episode_outline": "novelize_episode_outline",
    "novel_revise": "novelize_revise",
    "novel_revise_blocks": "novelize_revise",
    "novel_recheck": "novelize_revise_recheck",
    "novel_boundary": "novelize_boundary",
}
# 작업 모델이 문안 체인과 부를 모델을 정하는 단계. 나머지 넷은 작업 모델과 무관하다.
_NOVEL_JOB_MODEL_STAGES = frozenset({"novel_chapter", "novel_outline", "novel_episode_outline"})


def _novel_cases() -> list[dict[str, Any]]:
    """기본값 하나, 경로마다(직결·Bedrock) 화 생성만 배정(구성안 둘은 물려받음)·구성안 둘만 배정·소설 호출 위치 전부 배정, 그리고
    소설 Gemini 모델명을 비운 케이스."""
    cases: list[dict[str, Any]] = [{"name": "defaults", "settings": {}}]
    novel_sites = sorted(set(_NOVEL_STAGE_CALL_SITES.values()))
    for assign in ("anthropic", "bedrock"):
        cases.append(
            {"name": f"chapter-on-{assign}", "settings": {"llm_call_site_backends": {"novelize_chapter": assign}}}
        )
        cases.append(
            {
                "name": f"outlines-on-{assign}",
                "settings": {
                    "llm_call_site_backends": {"novelize_outline": assign, "novelize_episode_outline": assign}
                },
            }
        )
        cases.append(
            {
                "name": f"every-novel-call-site-on-{assign}",
                "settings": {"llm_call_site_backends": dict.fromkeys(novel_sites, assign)},
            }
        )
    cases.append({"name": "novelize-model-name-empty", "settings": {"gemini_novelize_model_name": ""}})
    return cases


def _novel_route_today(stage: str, job_model: ChatModelId) -> list[str]:
    """그 소설 단계가 그 작업 모델로 지금 읽는 체인·부르는 모델·경로·실제 모델 id. 체인은 화 생성·구성안이면 작업 모델, 나머지는
    소설 문안 체인 읽기의 기본 인자다. 모델·경로는 공급자 구현을 고르는 라우터와 같은 인자로 푼다 — 스트림 호출은 실린 모델,
    구조화 호출은 `structured_call_model` 이 고른 모델을 `pick_backend` 에 넘긴다."""
    call_site = _NOVEL_STAGE_CALL_SITES[stage]
    default_chain: ChatModelId = inspect.signature(load_novel_prompt_source).parameters["model"].default
    chain = job_model if stage in _NOVEL_JOB_MODEL_STAGES else default_chain
    routed = (
        job_model if CALL_POLICIES[call_site].call_kind == "stream" else structured_call_model(call_site, job_model)
    )
    model, backend = pick_backend(
        call_site, routed, settings.llm_call_site_backends, call_model=configured_call_site_model(call_site)
    )
    return [chain, model, backend, _model_id(call_site, backend, model)]


@pytest.mark.skipif(
    not os.environ.get(_NOVEL_WRITE_SWITCH), reason=f"{_NOVEL_WRITE_SWITCH}=1 일 때만 기대값 파일을 쓴다"
)
def test_write_the_novel_empty_table_expected_routes(fixed_settings: pytest.MonkeyPatch) -> None:
    rows: list[list[str]] = []
    for case in _novel_cases():
        with fixed_settings.context() as patch:
            for name, value in case["settings"].items():
                patch.setattr(settings, name, value)
            for stage, call_site in _NOVEL_STAGE_CALL_SITES.items():
                by_job_model = {model: _novel_route_today(stage, model) for model in get_args(ChatModelId)}
                if stage in _NOVEL_JOB_MODEL_STAGES:
                    rows.extend(
                        [case["name"], model, stage, call_site, *route] for model, route in by_job_model.items()
                    )
                    continue
                distinct = {tuple(route) for route in by_job_model.values()}
                assert len(distinct) == 1, (case["name"], stage, by_job_model)
                rows.append([case["name"], "*", stage, call_site, *by_job_model["gemini"]])
    expected = {
        "fixedSettings": _FIXED_SETTINGS,
        "cases": _novel_cases(),
        "stageCallSites": _NOVEL_STAGE_CALL_SITES,
        "columns": ["case", "jobModel", "stage", "callSite", "chainModel", "callModel", "backend", "modelId"],
        "rows": rows,
    }
    _NOVEL_EXPECTED_PATH.write_text(json.dumps(expected, ensure_ascii=False, sort_keys=True) + "\n")


def _resolve(
    routes: PromptRoutes,
    lane: RoutingLane,
    room_model: RouteRoomModel,
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

    # 이 기대값은 채팅 두 레인과 그 단계만 적는다(소설 레인은 아래 따로 둔 기대값이 본다). 방 모델은 기대값을 만들 때 채팅에서
    # 고를 수 있던 둘이다 — 그 뒤 채팅에 연 Sonnet 방의 생성 줄은 기대값 파일에 없고, 해석 함수로 새로 만들면 대조가 항진명제가
    # 되므로 Sonnet 방은 아래 운영 env 해석 테스트가 따로 본다.
    chat_stages = {stage for lane in get_args(ChatRoutingLane) for stage in LANE_STAGES[lane]}
    compared = 0
    for case in expected["cases"]:
        with fixed_settings.context() as patch:
            for name, value in case["settings"].items():
                patch.setattr(settings, name, value)
            for lane in get_args(ChatRoutingLane):
                for room_model in ("gemini", "opus"):
                    for stage, spec in STAGES.items():
                        if stage not in chat_stages:
                            continue
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


def test_an_empty_table_resolves_every_novel_cell_the_way_the_novel_calls_go_today(
    fixed_settings: pytest.MonkeyPatch,
) -> None:
    """소설 레인이 표에 들어와도 행이 없으면 소설 호출이 지금 읽는 체인·부르는 모델·경로가 그대로여야 한다. 기대값은 해석 함수가
    소설 레인을 풀기 전 코드에서 기록했다(모듈 docstring)."""
    expected = json.loads(_NOVEL_EXPECTED_PATH.read_text())
    assert expected["fixedSettings"] == _FIXED_SETTINGS
    assert expected["cases"] == _novel_cases()
    assert expected["stageCallSites"] == {stage: stage_call_sites(stage)[0] for stage in LANE_STAGES["novel"]}
    assert [len(stage_call_sites(stage)) for stage in LANE_STAGES["novel"]] == [1] * 7
    by_key = {(row[0], row[1], row[2]): row[4:] for row in expected["rows"]}

    compared = 0
    for case in expected["cases"]:
        with fixed_settings.context() as patch:
            for name, value in case["settings"].items():
                patch.setattr(settings, name, value)
            for stage in LANE_STAGES["novel"]:
                for room_model in stage_room_models("novel", stage):
                    route = _resolve(PromptRoutes.empty(), "novel", room_model, stage)
                    call_site = stage_call_sites(stage)[0]
                    actual = [
                        route.chain_model,
                        route.call_model,
                        route.backend,
                        _model_id(call_site, route.backend, route.call_model),
                    ]
                    room_key = "*" if room_model == "any" else room_model
                    assert actual == by_key[(case["name"], room_key, stage)], (case["name"], room_model, stage)
                    assert route.skipped is None
                    compared += 1
    assert compared == len(expected["cases"]) * (3 * 3 + 4)
    assert compared == len(expected["rows"])


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
    room_model: RouteRoomModel = "opus",
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
            for room_model in stage_room_models(lane, stage):
                assert _resolve(PromptRoutes.empty(), lane, room_model, stage).skipped is None


# --- 소설 레인 --------------------------------------------------------------------------------------------------------
# 운영 env 는 소설 화 생성 호출 위치를 직결로 배정하고(구성안 둘은 물려받는다), 소설 구조화 호출 위치는 배정하지 않는다.
_NOVEL_CHAPTER_ON_ANTHROPIC = {"novelize_chapter": "anthropic"}


def test_a_novel_generation_row_resolves_to_the_job_model_and_its_path_must_match_the_env(
    fixed_settings: pytest.MonkeyPatch,
) -> None:
    """소설 생성 행은 체인·부를 모델을 고르지 않는다 — 늘 작업 모델이고(차감이 작업 모델 단가다), 경로는 env 배정과 같을 때만
    쓰인다. 그래서 행이 있든 없든 값이 env 규칙과 같다."""
    fixed_settings.setattr(settings, "llm_call_site_backends", _NOVEL_CHAPTER_ON_ANTHROPIC)
    routes = PromptRoutes.from_rows(
        [
            _row("novel_chapter", lane="novel", room_model="sonnet", chain_model=None, call_model="sonnet"),
            _row("novel_outline", lane="novel", room_model="opus", chain_model=None, call_model="opus"),
        ]
    )

    cells: tuple[tuple[RouteRoomModel, str], ...] = (("sonnet", "novel_chapter"), ("opus", "novel_outline"))
    for room_model, stage in cells:
        with_row = _resolve(routes, "novel", room_model, stage)
        without = _resolve(PromptRoutes.empty(), "novel", room_model, stage)
        assert (with_row.chain_model, with_row.call_model, with_row.backend, with_row.source) == (
            room_model,
            room_model,
            "anthropic",
            "row",
        )
        assert (with_row.chain_model, with_row.call_model, with_row.backend) == (
            without.chain_model,
            without.call_model,
            without.backend,
        )

    fixed_settings.setattr(settings, "llm_call_site_backends", {})
    drifted = _resolve(routes, "novel", "sonnet", "novel_chapter")
    assert (drifted.chain_model, drifted.call_model, drifted.backend, drifted.source) == (
        "sonnet",
        "sonnet",
        "bedrock",
        "room",
    )
    assert drifted.skipped is not None
    assert drifted.skipped.reason == "backend-mismatch"


def test_a_novel_structured_claude_row_is_applied_when_its_call_site_is_assigned_to_the_direct_route(
    fixed_settings: pytest.MonkeyPatch,
) -> None:
    """소설 구조화 호출 위치를 직결로 배정하는 env 는 기동 검증이 거부하는 조합이라(그 호출 위치의 모델은 기본 모델 Gemini 로만
    본다) 설정 패치로만 만든다 — 운영에서 이 행이 쓰이려면 그 검증을 고치는 후속 작업이 먼저다. 여기서는 배정이 맞으면 행의 체인과
    부를 모델이 그대로 쓰인다는 해석 규칙만 고정한다."""
    fixed_settings.setattr(settings, "llm_call_site_backends", {"novelize_revise": "anthropic"})
    routes = PromptRoutes.from_rows([_row("novel_revise", lane="novel", room_model="any", chain_model="sonnet")])

    route = _resolve(routes, "novel", "any", "novel_revise")

    assert (route.chain_model, route.call_model, route.backend, route.source) == ("sonnet", "haiku", "anthropic", "row")
    assert route.skipped is None


def test_a_novel_structured_claude_row_is_skipped_while_its_call_site_has_no_direct_assignment(
    fixed_settings: pytest.MonkeyPatch,
) -> None:
    """운영 env 그대로다. 배정이 없으면 Claude 모델은 기본 구현 Bedrock 으로 가 행의 직결 경로와 맞지 않으므로, 그 칸은 지금처럼
    Gemini 체인·Gemini 모델로 돈다."""
    fixed_settings.setattr(settings, "llm_call_site_backends", _NOVEL_CHAPTER_ON_ANTHROPIC)
    routes = PromptRoutes.from_rows([_row("novel_boundary", lane="novel", room_model="any", chain_model="opus")])

    route = _resolve(routes, "novel", "any", "novel_boundary")

    assert (route.chain_model, route.call_model, route.backend, route.source) == ("gemini", "gemini", "gemini", "env")
    assert route.skipped is not None
    assert (route.skipped.stage, route.skipped.reason) == ("novel_boundary", "backend-mismatch")


def test_the_two_revise_stages_read_their_own_rows_though_they_share_a_call_site(
    fixed_settings: pytest.MonkeyPatch,
) -> None:
    """문단 수정과 여러 문단 수정은 같은 호출 위치를 쓰지만 단계가 다르다. 한쪽 행이 다른 쪽 칸에 새면 여러 문단 수정이 문단
    수정의 체인으로 렌더된다."""
    fixed_settings.setattr(settings, "llm_call_site_backends", {"novelize_revise": "anthropic"})
    revise_only = PromptRoutes.from_rows(
        [_row("novel_revise", lane="novel", room_model="any", chain_model="opus", call_model="sonnet")]
    )
    blocks_only = PromptRoutes.from_rows(
        [_row("novel_revise_blocks", lane="novel", room_model="any", chain_model="opus", call_model="sonnet")]
    )

    def picked(routes: PromptRoutes, stage: str) -> tuple[str, str, str]:
        route = _resolve(routes, "novel", "any", stage)
        return (route.chain_model, route.call_model, route.source)

    assert picked(revise_only, "novel_revise") == ("opus", "sonnet", "row")
    assert picked(revise_only, "novel_revise_blocks") == ("gemini", "gemini", "env")
    assert picked(blocks_only, "novel_revise") == ("gemini", "gemini", "env")
    assert picked(blocks_only, "novel_revise_blocks") == ("opus", "sonnet", "row")


def test_a_novel_cell_outside_its_axis_is_a_caller_bug(fixed_settings: pytest.MonkeyPatch) -> None:
    """구조화 소설 칸은 작업 모델과 무관한 `any` 칸 하나다. 작업 모델을 넘기면 행을 못 찾아 조용히 env 로 가므로 부르는 쪽의
    버그로 드러낸다. 생성 칸에 `any` 를 넘기는 것도 같다."""
    with pytest.raises(ValueError, match="novel_revise"):
        _resolve(PromptRoutes.empty(), "novel", "opus", "novel_revise")
    with pytest.raises(ValueError, match="novel_chapter"):
        _resolve(PromptRoutes.empty(), "novel", "any", "novel_chapter")


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


def test_a_row_assigned_for_chat_but_otherwise_for_preview_is_a_backend_mismatch(save_env: pytest.MonkeyPatch) -> None:
    """미리보기 줄이 채팅 줄과 다른 env(기동 검증이 거부하는 env 다)에서는 행이 미리보기 경로와 맞지 않는다."""
    assignments = {**_JUDGMENTS_ON_ANTHROPIC["llm_call_site_backends"], "preview_ending_judgment": "bedrock"}
    save_env.setattr(settings, "llm_call_site_backends", assignments)

    errors = route_row_errors([_input("ending_judgment")])

    assert [(error.index, error.rule) for error in errors] == [(0, "backend-mismatch")]
    assert "preview_ending_judgment" in errors[0].message


def test_a_row_assigned_for_chat_fits_a_preview_without_its_own_line(save_env: pytest.MonkeyPatch) -> None:
    """미리보기 판정 줄이 없으면 미리보기는 채팅 짝의 배정을 물려받아 같은 경로로 간다 — 행을 그대로 쓸 수 있다."""
    assignments = dict(_JUDGMENTS_ON_ANTHROPIC["llm_call_site_backends"])
    del assignments["preview_ending_judgment"]
    save_env.setattr(settings, "llm_call_site_backends", assignments)

    assert route_row_errors([_input("ending_judgment")]) == []


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


def test_a_parsed_novel_row_keeps_its_cell_and_a_row_off_the_novel_axes_is_none() -> None:
    """캐시·DB 에서 읽은 소설 행도 같은 함수를 지난다. 축 밖 행이 읽히면 아무도 저장할 수 없었던 칸이 해석에 쓰인다."""
    revise = _input("novel_revise", lane="novel", room_model="any", chain_model="sonnet")
    chapter = _input("novel_chapter", lane="novel", room_model="sonnet", chain_model=None, call_model="sonnet")

    assert parse_route_row(revise) == _row("novel_revise", lane="novel", room_model="any", chain_model="sonnet")
    assert parse_route_row(chapter) == _row(
        "novel_chapter", lane="novel", room_model="sonnet", chain_model=None, call_model="sonnet"
    )
    assert parse_route_row(_input("novel_revise", lane="novel", room_model="any", chain_model="haiku")) is None
    assert parse_route_row(_input("novel_revise", lane="novel", room_model="gemini", chain_model="gemini")) is None
    assert (
        parse_route_row(_input("novel_chapter", lane="novel", room_model="any", chain_model=None, call_model="sonnet"))
        is None
    )
    assert (
        parse_route_row(_input("novel_outline", lane="novel", room_model="opus", chain_model=None, call_model="gemini"))
        is None
    )


def _with_novel_assignments(save_env: pytest.MonkeyPatch, novel: dict[str, str]) -> None:
    save_env.setattr(settings, "llm_call_site_backends", {**_JUDGMENTS_ON_ANTHROPIC["llm_call_site_backends"], **novel})


def test_novel_generation_rows_on_the_env_path_of_their_job_model_save(save_env: pytest.MonkeyPatch) -> None:
    """Sonnet 작업의 화 생성 직결 행은 소설 생성에서만 고를 수 있는 쌍이다. 구성안은 화 생성 호출 위치의 배정을 물려받는다."""
    _with_novel_assignments(save_env, {"novelize_chapter": "anthropic"})
    rows = [
        _input("novel_chapter", lane="novel", room_model="sonnet", chain_model=None, call_model="sonnet"),
        _input("novel_outline", lane="novel", room_model="opus", chain_model=None, call_model="opus"),
        _input(
            "novel_episode_outline",
            lane="novel",
            room_model="gemini",
            chain_model=None,
            call_model="gemini",
            backend="gemini",
        ),
    ]

    assert route_row_errors(rows) == []
    assert ("sonnet", "anthropic") in ALLOWED_ROUTE_PAIRS["generation"]


@pytest.mark.parametrize(
    ("row", "rule"),
    [
        pytest.param(
            _input("novel_chapter", lane="novel", room_model="sonnet", chain_model="opus", call_model="sonnet"),
            "generation-chain",
            id="novel-generation-row-with-a-chain",
        ),
        pytest.param(
            _input("novel_outline", lane="novel", room_model="opus", chain_model=None, call_model="sonnet"),
            "generation-call-model",
            id="novel-generation-row-calling-another-model",
        ),
        pytest.param(
            _input("novel_chapter", lane="novel", room_model="any", chain_model=None, call_model="sonnet"),
            "unknown-stage",
            id="novel-generation-cell-without-a-job-model",
        ),
        pytest.param(
            _input("novel_revise", lane="novel", room_model="opus", chain_model="opus"),
            "unknown-stage",
            id="novel-structured-cell-keyed-by-a-job-model",
        ),
        pytest.param(
            _input("novel_chapter", room_model="sonnet", chain_model=None, call_model="sonnet"),
            "unknown-stage",
            id="novel-stage-in-a-chat-lane",
        ),
        pytest.param(
            _input("chat_generate", lane="novel", room_model="opus", chain_model=None, call_model="opus"),
            "unknown-stage",
            id="chat-stage-in-the-novel-lane",
        ),
        pytest.param(
            _input("novel_recheck", lane="novel", room_model="any", chain_model="haiku", call_model="gemini"),
            "chain-not-in-lane",
            id="novel-chain-the-lane-does-not-have",
        ),
        pytest.param(
            _input("novel_recheck", lane="novel", room_model="any", chain_model="haiku_writer", call_model="gemini"),
            "chain-not-in-lane",
            id="novel-chain-of-the-chat-only-haiku-writer",
        ),
        pytest.param(
            _input("novel_chapter", lane="novel", room_model="haiku_writer", chain_model=None, call_model="haiku_writer"),
            "unknown-stage",
            id="novel-generation-cell-of-the-chat-only-haiku-writer",
        ),
        pytest.param(
            _input("novel_boundary", lane="novel", room_model="any", chain_model="opus", call_model="opus"),
            "backend-mismatch",
            id="novel-structured-claude-row-without-a-direct-assignment",
        ),
        pytest.param(
            _input("novel_chapter", lane="novel", room_model="opus", chain_model=None, call_model="opus"),
            "backend-mismatch",
            id="novel-generation-row-off-its-env-path",
        ),
        pytest.param(
            _input("chat_generate", room_model="opus", chain_model=None, call_model="sonnet"),
            "generation-call-model",
            id="chat-generation-still-calls-only-the-room-model",
        ),
    ],
)
def test_a_novel_row_breaking_a_save_rule_is_refused_by_that_rule(
    save_env: pytest.MonkeyPatch, row: RouteRowInput, rule: str
) -> None:
    assert _rules([row]) == [(0, rule)]


def test_a_novel_structured_claude_row_saves_once_its_call_site_is_assigned_to_the_direct_route(
    save_env: pytest.MonkeyPatch,
) -> None:
    """기동 검증이 거부하는 env 라 설정 패치로만 만든다(해석 쪽 같은 테스트의 docstring). 저장 검사도 그 배정에서는 행을 받는다."""
    _with_novel_assignments(save_env, {"novelize_revise": "anthropic", "novelize_revise_recheck": "anthropic"})
    rows = [
        _input("novel_revise", lane="novel", room_model="any", chain_model="sonnet", call_model="opus"),
        _input("novel_revise_blocks", lane="novel", room_model="any", chain_model="gemini", call_model="sonnet"),
        _input("novel_recheck", lane="novel", room_model="any", chain_model="gemini", call_model="haiku"),
        _input(
            "novel_boundary", lane="novel", room_model="any", chain_model="opus", call_model="gemini", backend="gemini"
        ),
    ]

    assert route_row_errors(rows) == []


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


# --- 채팅에 연 Sonnet 방 ------------------------------------------------------------------------------------------------


def test_a_sonnet_room_generation_row_on_bedrock_is_refused_and_never_applied(save_env: pytest.MonkeyPatch) -> None:
    """Sonnet 방 칸이 열려 생성 행을 저장할 수 있게 됐어도 경로는 직결뿐이다 — Bedrock 경로를 env 가 받쳐도 저장 검사가
    거부하고, 표에 들어와 있어도 해석이 쓰지 않고 방 규칙으로 돈다. 직결 행과 판정 행은 저장된다."""
    sonnet_on_bedrock = _input("chat_generate", room_model="sonnet", chain_model=None, call_model="sonnet", backend="bedrock")
    save_env.setattr(settings, "llm_call_site_backends", {"chat_generate": "bedrock"})
    save_env.setattr(settings, "bedrock_access_key_id", "AKIATEST")
    save_env.setattr(settings, "bedrock_secret_access_key", "secret")
    save_env.setattr(settings, "bedrock_region", "ap-northeast-2")

    refused = _rules([sonnet_on_bedrock])
    route = _resolve(
        PromptRoutes.from_rows(
            [_row("chat_generate", room_model="sonnet", chain_model=None, call_model="sonnet", backend="bedrock")]
        ),
        "story",
        "sonnet",
        "chat_generate",
    )

    assert refused == [(0, "pair-not-allowed")]
    assert route.source == "room"
    assert route.skipped is not None
    assert route.skipped.reason == "pair-not-allowed"


def test_sonnet_room_rows_on_the_direct_route_save(save_env: pytest.MonkeyPatch) -> None:
    rows = [
        _input("chat_generate", room_model="sonnet", chain_model=None, call_model="sonnet"),
        _input("memory_fact", lane="character", room_model="sonnet"),
    ]

    assert route_row_errors(rows) == []


def _use_production_env(monkeypatch: pytest.MonkeyPatch) -> Settings:
    loaded = load_production_env(monkeypatch)
    for name in Settings.model_fields:
        monkeypatch.setattr(settings, name, getattr(loaded, name))
    return loaded


def test_production_env_sends_sonnet_generation_direct_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    """운영 env 에는 Sonnet 을 위한 줄이 따로 없다 — 채팅 생성·측정용 다시 생성 배정이 Sonnet 에도 걸리고, 미리보기 생성은 채팅
    생성의 배정을 물려받는다. 셋 다 Bedrock 이 아니라 직결이어야 한다."""
    loaded = _use_production_env(monkeypatch)

    for call_site in ("chat_generate", "preview_generate", "replay_generate"):
        assert pick_backend(call_site, "sonnet", loaded.llm_call_site_backends) == ("sonnet", "anthropic"), call_site
    for lane in get_args(ChatRoutingLane):
        route = _resolve(PromptRoutes.empty(), lane, "sonnet", "chat_generate")
        assert (route.call_model, route.backend, route.source) == ("sonnet", "anthropic", "room"), lane


def test_production_env_judges_a_sonnet_room_with_haiku_on_the_direct_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """운영 행은 스토리 Opus 방의 스탯 판정 하나다. Sonnet 방 칸에는 행이 없어 판정·요약·추출은 모델 설정(Haiku)과 env 배정(직결)으로
    풀리고 — Gemini 방과 같은 경로다 — Opus 칸의 행이 Sonnet 칸으로 번지지 않는다. 그 행의 Opus 칸 해석은 그대로다."""
    _use_production_env(monkeypatch)
    routes = PromptRoutes.from_rows([_row("stat_judgment", room_model="opus", chain_model="haiku", call_model="haiku")])

    compared = 0
    for lane in get_args(ChatRoutingLane):
        for stage in LANE_STAGES[lane]:
            if STAGES[stage].kind != "structured":
                continue
            for call_site in stage_call_sites(stage):
                route = _resolve(routes, lane, "sonnet", stage, call_site)
                assert (route.source, route.call_model, route.backend, route.skipped) == (
                    "env",
                    "haiku",
                    "anthropic",
                    None,
                ), (lane, stage, call_site)
                compared += 1
    opus_stat = _resolve(routes, "story", "opus", "stat_judgment")

    assert compared > 0
    assert (opus_stat.source, opus_stat.chain_model, opus_stat.call_model, opus_stat.backend) == (
        "row",
        "haiku",
        "haiku",
        "anthropic",
    )


def test_the_judgment_only_model_stays_off_the_chat_room_axis() -> None:
    """판정 전용 `haiku` 는 글쓰기 모델도 방 모델도 아니다 — 방 모델 축을 넓혀도 그 값으로 글을 쓰는 방 칸은 생기지 않는다."""
    assert "haiku" not in get_args(ChatModelId)
    for lane in get_args(ChatRoutingLane):
        for stage in LANE_STAGES[lane]:
            assert "haiku" not in stage_room_models(lane, stage), (lane, stage)


# --- 채팅에 연 Haiku 글쓰기 방 ------------------------------------------------------------------------------------------


def test_a_haiku_writer_room_generation_row_on_bedrock_is_refused_and_never_applied(save_env: pytest.MonkeyPatch) -> None:
    """Haiku 글쓰기 생성 경로는 직결뿐이다 — Bedrock 행은 저장 검사가 거부하고, 표에 들어와 있어도 해석이 방 규칙(직결)으로 돈다."""
    save_env.setattr(settings, "llm_call_site_backends", {"chat_generate": "bedrock"})
    save_env.setattr(settings, "bedrock_access_key_id", "AKIATEST")
    save_env.setattr(settings, "bedrock_secret_access_key", "secret")
    save_env.setattr(settings, "bedrock_region", "ap-northeast-2")

    refused = _rules(
        [_input("chat_generate", room_model="haiku_writer", chain_model=None, call_model="haiku_writer", backend="bedrock")]
    )
    route = _resolve(
        PromptRoutes.from_rows(
            [
                _row(
                    "chat_generate",
                    room_model="haiku_writer",
                    chain_model=None,
                    call_model="haiku_writer",
                    backend="bedrock",
                )
            ]
        ),
        "story",
        "haiku_writer",
        "chat_generate",
    )

    assert refused == [(0, "pair-not-allowed")]
    assert (route.source, route.call_model, route.backend) == ("room", "haiku_writer", "anthropic")
    assert route.skipped is not None
    assert route.skipped.reason == "pair-not-allowed"


def test_the_writer_only_haiku_is_not_a_judgment_pair() -> None:
    """판정은 판정 전용 `haiku` 가 맡는다 — 글쓰기 id 를 부를 모델로 고른 판정 행은 허용 목록 밖이다."""
    assert ("haiku_writer", "anthropic") in ALLOWED_ROUTE_PAIRS["generation"]
    assert all(model != "haiku_writer" for model, _ in ALLOWED_ROUTE_PAIRS["structured"])


def test_production_env_writes_a_haiku_writer_room_direct_and_judges_it_with_the_judgment_only_haiku(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """운영 env 와 운영 행 하나(스토리 Opus 방의 스탯 판정)에서, 표가 빈 Haiku 글쓰기 방의 생성은 방 모델로 직결에 가고, 판정·요약·
    추출 단계는 모델 설정(판정 전용 `haiku`)과 env 배정(직결)으로 풀린다 — 읽는 체인도 판정 전용 `haiku` 다. Bedrock 기본(Haiku
    4.5)으로 가지 않는 근거는 운영 배정이라 운영 env 로 고정한다. Opus 칸의 행은 번지지 않는다."""
    _use_production_env(monkeypatch)
    routes = PromptRoutes.from_rows([_row("stat_judgment", room_model="opus", chain_model="haiku", call_model="haiku")])

    compared = 0
    for lane in get_args(ChatRoutingLane):
        generation = _resolve(routes, lane, "haiku_writer", "chat_generate")
        assert (generation.source, generation.call_model, generation.backend) == (
            "room",
            "haiku_writer",
            "anthropic",
        ), lane
        for stage in LANE_STAGES[lane]:
            if STAGES[stage].kind != "structured":
                continue
            for call_site in stage_call_sites(stage):
                route = _resolve(routes, lane, "haiku_writer", stage, call_site)
                assert (route.source, route.chain_model, route.call_model, route.backend, route.skipped) == (
                    "env",
                    "haiku",
                    "haiku",
                    "anthropic",
                    None,
                ), (lane, stage, call_site)
                compared += 1
    opus_stat = _resolve(routes, "story", "opus", "stat_judgment")

    assert compared > 0
    assert (opus_stat.source, opus_stat.chain_model, opus_stat.call_model, opus_stat.backend) == (
        "row",
        "haiku",
        "haiku",
        "anthropic",
    )


def test_the_haiku_writer_room_is_on_the_chat_axes_but_not_on_the_novel_axis() -> None:
    for lane in get_args(ChatRoutingLane):
        for stage in LANE_STAGES[lane]:
            assert "haiku_writer" in stage_room_models(lane, stage), (lane, stage)
    for stage in LANE_STAGES["novel"]:
        assert "haiku_writer" not in stage_room_models("novel", stage), stage
