"""모델 배정 표(`prompt_routes`)의 해석.

한 칸은 (레인, 실효 방 모델, 단계)다. 칸마다 어느 프롬프트 체인을 읽고(`chain_model`), 어느 모델을(`call_model`) 어느
경로로(`backend`) 부를지 정한다. 표가 비었거나 그 칸의 행이 없으면 지금까지의 env 규칙과 같은 값을 낸다.

해석은 DB·Redis 를 부르지 않는 동기 순수 함수다 — 표는 인자로 받고(읽기는 `chat/prompt_routing_cache.py`), env 배정·모델
설정은 호출마다 `settings` 에서 읽는다(import 때 붙잡으면 테스트가 바꾼 설정이 실리지 않는다).
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from api.chat.prompt_stages import LANE_STAGES, STAGES, PromptStage, RoutingLane, StageKind, stage_call_sites
from api.core.config import settings
from api.llm.backends import pick_backend, structured_effort_error
from api.llm.call_policy import CALL_POLICIES, BackendId, LLMCallSite
from api.llm.chat_models import ChatRoomModelId, PromptSetModelId, configured_call_site_model

# 칸의 값이 어디서 왔는가. `row` 는 그 칸의 행, `inherited` 는 물려받은 단계의 행, `env` 는 판정·요약 모델 설정과 env 배정,
# `room` 은 생성 단계의 방 모델과 env 배정이다. 행이 있었지만 쓰지 않았으면 출처는 `env`·`room` 이고 `StageRoute.skipped` 에
# 그 행과 이유가 남는다.
RouteSource = Literal["row", "inherited", "env", "room"]

# 저장된 행을 해석이 건너뛰는 이유. 저장 검사는 저장 시점의 env 로 이 셋을 이미 막지만, 저장 뒤 env 배정·모델 id·구조화 깊이가
# 바뀌면 행이 실제 경로와 어긋날 수 있다. 그때 행을 그대로 믿으면 표시와 실제가 다르거나 매 판정이 실패하므로, 기동 검증을 통과한
# env 규칙으로 돌아간다.
# - `pair-not-allowed`: (부를 모델, 경로)가 허용 목록 밖이다.
# - `backend-mismatch`: 그 행을 읽는 호출 위치 중 하나에서 env 배정으로 푼 경로가 행의 경로와 다르다.
# - `structured-effort`: Anthropic 직결 판정이 사고를 끄는 모델로 가는데 구조화 깊이가 그 요청이 받는 범위 밖이다.
SkipReason = Literal["pair-not-allowed", "backend-mismatch", "structured-effort"]

# 단계 종류마다 행이 고를 수 있는 (부를 모델, 경로). 처리방침에 적은 수탁자 경로(Google·Anthropic 직결)만 둔다 — Bedrock 쌍이
# 없는 이유다. 등록부에서 Claude 모델의 기본 구현이 Bedrock 이라, 배정 없이 Claude 모델을 고른 행은 경로 대조에서도 걸린다.
# 생성은 방 모델로만 부르므로(대화 차감이 방 모델 단가다) 방에서 고를 수 있는 모델의 쌍뿐이다. 어드민 저장 검사와 해석이 이 목록
# 하나를 함께 읽는다.
ALLOWED_ROUTE_PAIRS: dict[StageKind, frozenset[tuple[PromptSetModelId, BackendId]]] = {
    "structured": frozenset(
        {("gemini", "gemini"), ("haiku", "anthropic"), ("sonnet", "anthropic"), ("opus", "anthropic")}
    ),
    "generation": frozenset({("gemini", "gemini"), ("opus", "anthropic")}),
}


@dataclass(frozen=True, kw_only=True)
class RouteRow:
    """표의 한 행. 생성 행은 체인이 없다(늘 방 모델의 체인을 읽는다)."""

    lane: RoutingLane
    room_model: ChatRoomModelId
    stage: PromptStage
    chain_model: PromptSetModelId | None
    call_model: PromptSetModelId
    backend: BackendId


RouteKey = tuple[RoutingLane, ChatRoomModelId, PromptStage]


@dataclass(frozen=True)
class PromptRoutes:
    """표 전체의 읽기 전용 사상."""

    rows: Mapping[RouteKey, RouteRow] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "PromptRoutes":
        return cls()

    @classmethod
    def from_rows(cls, rows: Iterable[RouteRow]) -> "PromptRoutes":
        """한 칸에 행이 둘이면 `ValueError` — DB 는 유니크 인덱스로, 저장 요청은 저장 검사로 막으므로 부르는 쪽의 버그다."""
        by_key: dict[RouteKey, RouteRow] = {}
        for row in rows:
            key = (row.lane, row.room_model, row.stage)
            if key in by_key:
                raise ValueError(f"한 칸에 행이 둘이다: {key}")
            by_key[key] = row
        return cls(by_key)

    def get(self, lane: RoutingLane, room_model: ChatRoomModelId, stage: PromptStage) -> RouteRow | None:
        return self.rows.get((lane, room_model, stage))


@dataclass(frozen=True, kw_only=True)
class RouteSkip:
    """해석이 건너뛴 행. `stage` 는 그 행의 단계다(물려받으려던 행이면 물려준 단계)."""

    stage: PromptStage
    reason: SkipReason
    message: str


@dataclass(frozen=True, kw_only=True)
class StageRoute:
    chain_model: PromptSetModelId
    call_model: PromptSetModelId
    backend: BackendId
    source: RouteSource
    # 출처의 세부. `row`·`room` 이면 None, `inherited` 면 물려준 단계, `env` 면 모델 설정의 env 이름.
    source_detail: str | None
    # 그 칸에 쓸 행이 있었지만 쓰지 않았으면 그 행과 이유. 어드민 화면이 "적용 안 됨"을 보일 때 읽는다.
    skipped: RouteSkip | None = None


def _read_setting(name: str) -> str:
    return str(getattr(settings, name))


def row_call_sites(routes: PromptRoutes, row: RouteRow) -> tuple[LLMCallSite, ...]:
    """그 행을 읽는 호출 위치 전부 — 그 단계의 채팅·미리보기 호출 위치, 그리고 그 행을 물려받는 단계가 같은 (레인, 방 모델)에
    자기 행이 없으면 그 단계의 호출 위치도. 물려받는 쪽 호출 위치는 자기 env 배정을 먼저 보므로 물려준 단계와 경로가 다를 수 있다."""
    sites = list(stage_call_sites(row.stage))
    for stage in LANE_STAGES[row.lane]:
        if STAGES[stage].inherits_from == row.stage and routes.get(row.lane, row.room_model, stage) is None:
            sites.extend(stage_call_sites(stage))
    return tuple(sites)


def row_route_problem(
    row: RouteRow, call_sites: Iterable[LLMCallSite], read_setting: Callable[[str], str]
) -> tuple[SkipReason, str] | None:
    """그 행을 지금 env 로 그 호출 위치들에서 쓸 수 없으면 (이유, 문장), 쓸 수 있으면 None. DB 를 읽지 않는 순수 계산이다 —
    해석이 행마다 부르고, 어드민 저장 검사가 같은 판단을 저장 시점에 한다."""
    kind = STAGES[row.stage].kind
    if (row.call_model, row.backend) not in ALLOWED_ROUTE_PAIRS[kind]:
        return "pair-not-allowed", f"{row.call_model}@{row.backend} 는 이 단계가 고를 수 있는 모델·경로가 아니다"
    assignments = settings.llm_call_site_backends
    for call_site in call_sites:
        if kind == "generation":
            _, backend = pick_backend(call_site, row.room_model, assignments)
        else:
            # 판정 호출은 모델을 고를 수 없어, 부를 모델을 그 호출의 모델로 넘기지 않으면 env 모델의 경로를 보게 된다.
            _, backend = pick_backend(call_site, row.call_model, assignments, call_model=row.call_model)
        if backend != row.backend:
            return (
                "backend-mismatch",
                f"{call_site} 의 {row.call_model} 는 지금 배정으로 {backend} 로 간다(행은 {row.backend})",
            )
    if kind == "structured":
        effort_error = structured_effort_error(row.backend, row.call_model, read_setting)
        if effort_error is not None:
            return "structured-effort", effort_error
    return None


def _env_route(stage: PromptStage, call_site: LLMCallSite, room_model: ChatRoomModelId) -> StageRoute:
    """행이 없을 때 — 지금까지의 env 규칙과 같은 값. 판정·요약은 그 호출 위치의 모델 설정과 배정(`resolve_backend` 와 같은 인자),
    생성은 방 모델과 배정이다."""
    assignments = settings.llm_call_site_backends
    if STAGES[stage].kind == "generation":
        _, backend = pick_backend(call_site, room_model, assignments)
        return StageRoute(
            chain_model=room_model, call_model=room_model, backend=backend, source="room", source_detail=None
        )
    model = configured_call_site_model(call_site)
    _, backend = pick_backend(call_site, model, assignments, call_model=model)
    model_setting = CALL_POLICIES[call_site].model_setting
    return StageRoute(
        chain_model=model,
        call_model=model,
        backend=backend,
        source="env",
        source_detail=None if model_setting is None else model_setting.upper(),
    )


def resolve_stage_route(
    routes: PromptRoutes,
    *,
    lane: RoutingLane,
    room_model: ChatRoomModelId,
    stage: PromptStage,
    call_site: LLMCallSite | None = None,
) -> StageRoute:
    """(레인, 방 모델, 단계) 칸 하나의 읽을 체인·부를 모델·경로와 그 출처.

    1. 그 칸의 행이 있으면 그 행이다. 생성 행은 체인·부를 모델이 방 모델이고 경로만 행 값이다.
    2. 자기 행이 없고 물려받는 단계(장면 헤더 ← 스탯 판정)의 같은 (레인, 방 모델) 행이 있으면 그 행이다.
    3. 그 밖에는 env 규칙이다. 단계가 그 레인의 단계가 아니면 행이 있을 수 없어 늘 env 규칙이다.

    1·2 의 행도 그 행을 읽는 호출 위치 전부에서 지금 env 로 쓸 수 있을 때만 쓴다(`row_route_problem`). 아니면 3 으로 가고 건너뛴
    행과 이유를 `skipped` 에 남긴다. 한 행을 읽는 호출 위치들(채팅·미리보기, 물려받는 단계)이 함께 쓰거나 함께 건너뛰어, 같은
    행을 읽는 호출들이 서로 다른 모델로 가지 않는다.

    `call_site` 는 부르는 호출 위치이고 None 이면 그 단계의 채팅 호출 위치다. 그 단계의 호출 위치가 아니면 `ValueError`(부르는
    쪽의 버그)다. `lane` 이 채팅 레인이 아니면 `KeyError` 다."""
    stages = LANE_STAGES[lane]
    sites = stage_call_sites(stage)
    resolved_call_site = sites[0] if call_site is None else call_site
    if resolved_call_site not in sites:
        raise ValueError(f"{resolved_call_site} 는 {stage} 단계의 호출 위치가 아니다")

    if stage in stages:
        row = routes.get(lane, room_model, stage)
        source: RouteSource = "row"
        inherits_from = STAGES[stage].inherits_from
        if row is None and inherits_from is not None:
            row = routes.get(lane, room_model, inherits_from)
            source = "inherited"
        if row is not None:
            problem = row_route_problem(row, row_call_sites(routes, row), _read_setting)
            if problem is None:
                if row.chain_model is None:
                    return StageRoute(
                        chain_model=room_model,
                        call_model=room_model,
                        backend=row.backend,
                        source=source,
                        source_detail=None,
                    )
                return StageRoute(
                    chain_model=row.chain_model,
                    call_model=row.call_model,
                    backend=row.backend,
                    source=source,
                    source_detail=row.stage if source == "inherited" else None,
                )
            env = _env_route(stage, resolved_call_site, room_model)
            reason, message = problem
            return StageRoute(
                chain_model=env.chain_model,
                call_model=env.call_model,
                backend=env.backend,
                source=env.source,
                source_detail=env.source_detail,
                skipped=RouteSkip(stage=row.stage, reason=reason, message=message),
            )
    return _env_route(stage, resolved_call_site, room_model)
