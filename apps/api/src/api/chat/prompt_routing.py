"""모델 배정 표(`prompt_routes`)의 해석.

한 칸은 (레인, 실효 방 모델, 단계)다. 소설 레인은 방 모델 자리가 생성 단계에서 작업 모델, 작업 모델과 무관한 구조화 단계에서
표지 `any` 다. 칸마다 어느 프롬프트 체인을 읽고(`chain_model`), 어느 모델을(`call_model`) 어느
경로로(`backend`) 부를지 정한다. 표가 비었거나 그 칸의 행이 없으면 지금까지의 env 규칙과 같은 값을 낸다.

해석은 DB·Redis 를 부르지 않는 동기 순수 함수다 — 표는 인자로 받고(읽기는 `chat/prompt_routing_cache.py`), env 배정·모델
설정은 호출마다 `settings` 에서 읽는다(import 때 붙잡으면 테스트가 바꾼 설정이 실리지 않는다).
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_stages import (
    LANE_STAGES,
    STAGES,
    PromptStage,
    RouteRoomModel,
    RoutingLane,
    StageKind,
    stage_call_sites,
    stage_room_models,
)
from api.core.config import settings
from api.chat.prompt_builder import PromptSetNotFoundError, load_active_prompt_set
from api.llm.backends import BACKENDS, missing_credentials, pick_backend, structured_effort_error
from api.llm.call_policy import CALL_POLICIES, BackendId, LLMCallSite
from api.llm.chat_models import (
    ChatModelId,
    PromptSetModelId,
    configured_call_site_model,
    parse_chat_model_id,
    parse_prompt_set_model_id,
)

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
# 생성은 방 모델(소설은 작업 모델)로만 부르므로(차감이 그 모델 단가다) 고를 수 있는 글쓰기 모델의 쌍뿐이다. Sonnet 쌍은 소설
# 작업에만 있다 — 채팅 생성 칸은 방 모델 축(Gemini·Opus)이 막는다. 어드민 저장 검사와 해석이 이 목록 하나를 함께 읽는다.
ALLOWED_ROUTE_PAIRS: dict[StageKind, frozenset[tuple[PromptSetModelId, BackendId]]] = {
    "structured": frozenset(
        {("gemini", "gemini"), ("haiku", "anthropic"), ("sonnet", "anthropic"), ("opus", "anthropic")}
    ),
    "generation": frozenset({("gemini", "gemini"), ("sonnet", "anthropic"), ("opus", "anthropic")}),
}


@dataclass(frozen=True, kw_only=True)
class RouteRow:
    """표의 한 행. 생성 행은 체인이 없다(늘 방 모델·작업 모델의 체인을 읽는다)."""

    lane: RoutingLane
    room_model: RouteRoomModel
    stage: PromptStage
    chain_model: PromptSetModelId | None
    call_model: PromptSetModelId
    backend: BackendId


RouteKey = tuple[RoutingLane, RouteRoomModel, PromptStage]


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

    def get(self, lane: RoutingLane, room_model: RouteRoomModel, stage: PromptStage) -> RouteRow | None:
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


def _writing_model(room_model: RouteRoomModel, stage: PromptStage) -> ChatModelId:
    """생성 칸의 방 모델 자리(방 모델·작업 모델)를 글쓰기 모델로 읽는다. 생성 칸에 `any` 가 오면 부르는 쪽의 버그다 — 저장 검사와
    행 읽기가 그런 행을 막고, 해석은 그런 칸을 받지 않는다."""
    model = parse_chat_model_id(room_model)
    if model is None:
        raise ValueError(f"{stage} 생성 칸에는 작업 모델이 있어야 한다({room_model})")
    return model


def row_call_sites(routes: PromptRoutes, row: RouteRow) -> tuple[LLMCallSite, ...]:
    """그 행을 읽는 호출 위치 전부 — 그 단계의 채팅·미리보기 호출 위치, 그리고 그 행을 물려받는 단계가 같은 (레인, 방 모델)에
    자기 행이 없으면 그 단계의 호출 위치도. 물려받는 쪽 호출 위치는 자기 env 배정을 먼저 보므로 물려준 단계와 경로가 다를 수 있다."""
    sites = list(stage_call_sites(row.stage))
    for stage in LANE_STAGES[row.lane]:
        if STAGES[stage].inherits_from == row.stage and routes.get(row.lane, row.room_model, stage) is None:
            sites.extend(stage_call_sites(stage))
    return tuple(sites)


def _pair_problem(kind: StageKind, call_model: str, backend: str) -> str | None:
    if (call_model, backend) in ALLOWED_ROUTE_PAIRS[kind]:
        return None
    return f"{call_model}@{backend} 는 이 단계가 고를 수 있는 모델·경로가 아니다"


def _backend_problem(row: RouteRow, call_sites: Iterable[LLMCallSite]) -> str | None:
    assignments = settings.llm_call_site_backends
    for call_site in call_sites:
        if STAGES[row.stage].kind == "generation":
            _, backend = pick_backend(call_site, _writing_model(row.room_model, row.stage), assignments)
        else:
            # 판정 호출은 모델을 고를 수 없어, 부를 모델을 그 호출의 모델로 넘기지 않으면 env 모델의 경로를 보게 된다.
            _, backend = pick_backend(call_site, row.call_model, assignments, call_model=row.call_model)
        if backend != row.backend:
            return f"{call_site} 의 {row.call_model} 는 지금 배정으로 {backend} 로 간다(행은 {row.backend})"
    return None


def _effort_problem(row: RouteRow, read_setting: Callable[[str], str]) -> str | None:
    if STAGES[row.stage].kind != "structured":
        return None
    return structured_effort_error(row.backend, row.call_model, read_setting)


def row_route_problem(
    row: RouteRow, call_sites: Iterable[LLMCallSite], read_setting: Callable[[str], str]
) -> tuple[SkipReason, str] | None:
    """그 행을 지금 env 로 그 호출 위치들에서 쓸 수 없으면 (이유, 문장), 쓸 수 있으면 None. DB 를 읽지 않는 순수 계산이다 —
    해석이 행마다 부르고, 어드민 저장 검사가 같은 세 검사를 저장 시점에 한다."""
    pair = _pair_problem(STAGES[row.stage].kind, row.call_model, row.backend)
    if pair is not None:
        return "pair-not-allowed", pair
    mismatch = _backend_problem(row, call_sites)
    if mismatch is not None:
        return "backend-mismatch", mismatch
    effort = _effort_problem(row, read_setting)
    if effort is not None:
        return "structured-effort", effort
    return None


def _env_route(stage: PromptStage, call_site: LLMCallSite, room_model: RouteRoomModel) -> StageRoute:
    """행이 없을 때 — 지금까지의 env 규칙과 같은 값. 판정·요약·소설 구조화 호출은 그 호출 위치의 모델 설정(없으면 기본 모델)과
    배정(`resolve_backend` 와 같은 인자), 생성은 방 모델(소설은 작업 모델)과 배정이다."""
    assignments = settings.llm_call_site_backends
    if STAGES[stage].kind == "generation":
        writing = _writing_model(room_model, stage)
        _, backend = pick_backend(call_site, writing, assignments)
        return StageRoute(chain_model=writing, call_model=writing, backend=backend, source="room", source_detail=None)
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
    room_model: RouteRoomModel,
    stage: PromptStage,
    call_site: LLMCallSite | None = None,
) -> StageRoute:
    """(레인, 방 모델, 단계) 칸 하나의 읽을 체인·부를 모델·경로와 그 출처.

    1. 그 칸의 행이 있으면 그 행이다. 생성 행은 체인·부를 모델이 방 모델(소설은 작업 모델)이고 경로만 행 값이다 — 경로도 아래
       검사로 env 배정과 같을 때만 쓰이므로, 생성 칸의 값은 행이 있든 없든 env 규칙과 같다.
    2. 자기 행이 없고 물려받는 단계(장면 헤더 ← 스탯 판정)의 같은 (레인, 방 모델) 행이 있으면 그 행이다.
    3. 그 밖에는 env 규칙이다. 단계가 그 레인의 단계가 아니면 행이 있을 수 없어 늘 env 규칙이다.

    1·2 의 행도 그 행을 읽는 호출 위치 전부에서 지금 env 로 쓸 수 있을 때만 쓴다(`row_route_problem`). 아니면 3 으로 가고 건너뛴
    행과 이유를 `skipped` 에 남긴다. 한 행을 읽는 호출 위치들(채팅·미리보기, 물려받는 단계)이 함께 쓰거나 함께 건너뛰어, 같은
    행을 읽는 호출들이 서로 다른 모델로 가지 않는다.

    `call_site` 는 부르는 호출 위치이고 None 이면 그 단계의 채팅 호출 위치(소설 단계는 소설 호출 위치)다. 그 단계의 호출 위치가
    아니면 `ValueError`(부르는 쪽의 버그)다. 그 레인의 단계인데 `room_model` 이 그 칸의 축 밖이면(소설 구조화 칸에 작업 모델,
    생성 칸에 `any`) 행을 못 찾고 조용히 env 로 가므로 역시 `ValueError` 다. `lane` 이 배정 표의 레인이 아니면 `KeyError` 다."""
    stages = LANE_STAGES[lane]
    sites = stage_call_sites(stage)
    resolved_call_site = sites[0] if call_site is None else call_site
    if resolved_call_site not in sites:
        raise ValueError(f"{resolved_call_site} 는 {stage} 단계의 호출 위치가 아니다")
    if stage in stages and room_model not in stage_room_models(lane, stage):
        raise ValueError(f"{room_model} 는 ({lane}, {stage}) 칸의 방 모델 축 밖이다")

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
                    model = _writing_model(room_model, stage)
                    return StageRoute(
                        chain_model=model,
                        call_model=model,
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


# 어드민 저장 검사의 규칙 이름. 저장 API 의 422 응답 `detail.rule` 로 나간다.
RouteRule = Literal[
    "unknown-stage",
    "lane-out-of-scope",
    "duplicate-row",
    "generation-chain",
    "chain-not-in-lane",
    "generation-call-model",
    "pair-not-allowed",
    "backend-mismatch",
    "missing-credentials",
    "structured-effort",
    "chain-not-published",
    "chain-missing-channel",
]


@dataclass(frozen=True, kw_only=True)
class RouteRowInput:
    """저장 요청의 한 행. 이력 스냅샷으로 되돌릴 때는 요청 검증을 거치지 않으므로 값 범위를 좁히지 않고 문자열로 받는다."""

    lane: str
    room_model: str
    stage: str
    chain_model: str | None
    call_model: str
    backend: str


@dataclass(frozen=True, kw_only=True)
class RouteRowError:
    """저장 요청의 `index` 번째 행이 어긴 첫 규칙."""

    index: int
    rule: RouteRule
    message: str


def _parse_lane(value: str) -> RoutingLane | None:
    for lane in LANE_STAGES:
        if lane == value:
            return lane
    return None


def _parse_room_model(lane: RoutingLane, stage: PromptStage, value: str) -> RouteRoomModel | None:
    """그 레인의 그 단계가 갖는 칸의 축 안 값만 받는다 — 채팅은 방에서 고를 수 있는 모델, 소설 생성은 작업 모델, 소설 구조화는
    `any` 하나다. 축 밖 칸의 행은 아무도 읽지 않는다."""
    for room_model in stage_room_models(lane, stage):
        if room_model == value:
            return room_model
    return None


def _parse_stage(lane: RoutingLane, value: str) -> PromptStage | None:
    for stage in LANE_STAGES[lane]:
        if stage == value:
            return stage
    return None


def _parse_backend(value: str) -> BackendId | None:
    for backend in BACKENDS:
        if backend == value:
            return backend
    return None


def _shape_problem(lane: RoutingLane, stage: PromptStage, chain_model: str | None) -> str | None:
    if STAGES[stage].kind == "generation":
        if chain_model is not None:
            if lane == "novel":
                return "소설 생성 행은 읽을 체인을 고르지 않는다(늘 작업 모델의 체인을 읽는다)"
            return "생성 행은 읽을 체인을 고르지 않는다(늘 방 모델의 체인을 읽는다)"
        return None
    if chain_model is None:
        return f"{stage} 행은 읽을 체인이 있어야 한다"
    if parse_prompt_set_model_id(chain_model) is None:
        return f"읽을 체인 {chain_model} 는 프롬프트 체인의 모델이 아니다"
    return None


def _lane_chain_problem(lane: RoutingLane, chain_model: str | None) -> str | None:
    """소설 레인에는 판정 전용 체인(haiku)이 없다 — 체인은 글쓰기 모델 셋뿐이다. 채팅 레인은 체인 모델 축 전부가 있다."""
    if lane == "novel" and chain_model is not None and parse_chat_model_id(chain_model) is None:
        return f"소설 레인에는 {chain_model} 체인이 없다(글쓰기 모델 체인만 있다)"
    return None


def _generation_call_model_message(lane: RoutingLane, room_model: RouteRoomModel) -> str:
    if lane == "novel":
        return f"소설 생성 행은 작업 모델({room_model})로만 부른다(소설 차감이 작업 모델 단가다)"
    return f"생성 행은 방 모델({room_model})로만 부른다(대화 차감이 방 모델 단가다)"


def parse_route_row(row: RouteRowInput) -> RouteRow | None:
    """값 범위(배정 표 레인, 그 레인의 단계, 그 칸의 방 모델 축, 모델 축, 경로)와 행 모양(생성은 체인 없음·방 모델(소설은 작업
    모델)로 부름, 나머지는 체인 있음, 소설 레인 체인은 글쓰기 모델)이 맞으면 타입이 붙은 행, 아니면 None. 허용 목록·경로·자격은
    보지 않는다 — DB·캐시에서 읽은 행을 해석에 넘길 때와 저장 검사가 값 범위를 통과한 행을 바꿀 때 같은 함수를 쓴다."""
    lane = _parse_lane(row.lane)
    if lane is None:
        return None
    stage = _parse_stage(lane, row.stage)
    if stage is None:
        return None
    room_model = _parse_room_model(lane, stage, row.room_model)
    call_model = parse_prompt_set_model_id(row.call_model)
    backend = _parse_backend(row.backend)
    if (
        room_model is None
        or call_model is None
        or backend is None
        or _shape_problem(lane, stage, row.chain_model) is not None
        or _lane_chain_problem(lane, row.chain_model) is not None
    ):
        return None
    if STAGES[stage].kind == "generation":
        if call_model != room_model:
            return None
        chain_model = None
    else:
        chain_model = parse_prompt_set_model_id(row.chain_model or "")
    return RouteRow(
        lane=lane, room_model=room_model, stage=stage, chain_model=chain_model, call_model=call_model, backend=backend
    )


def route_row_errors(rows: Sequence[RouteRowInput]) -> list[RouteRowError]:
    """저장 요청 전체의 동기 검사(DB 없이). 행마다 아래 순서로 보고 첫 위반에서 그 행을 멈춘다. 설정은 지금 `settings` 에서 읽는다.

    1. `unknown-stage` — 레인이 배정 표의 레인, 단계가 그 레인의 단계, 방 모델이 그 칸의 축 안(채팅은 방에서 고를 수 있는 모델,
       소설 생성은 작업 모델, 소설 구조화는 `any`).
    2. `duplicate-row` — 앞 행과 같은 칸.
    3. `generation-chain` — 생성 행에 체인이 옴 / 나머지 행에 체인이 없거나 체인이 모델 축 밖.
    4. `chain-not-in-lane` — 그 레인에 없는 체인(소설 레인의 판정 전용 체인).
    5. `generation-call-model` — 생성 행의 부를 모델이 방 모델(소설은 작업 모델)이 아님.
    6. `pair-not-allowed` — (부를 모델, 경로)가 허용 목록 밖.
    7. `backend-mismatch` — 그 행을 읽는 호출 위치마다 지금 env 배정으로 푼 경로가 행의 경로와 다름. 읽는 호출 위치에는 채팅과
       미리보기, 그리고 요청에 물려받는 단계(장면 헤더)의 행이 없으면 그 단계의 호출 위치도 든다.
    8. `missing-credentials` — 그 경로의 자격이 빔.
    9. `structured-effort` — 판정 행이 Anthropic 직결에서 사고를 끄는 모델로 가는데 구조화 깊이가 그 요청이 받는 범위 밖.

    체인의 게시 여부와 채널은 `route_chain_errors` 가 본다(DB)."""
    errors: list[RouteRowError] = []
    seen: dict[RouteKey, int] = {}
    staged: list[tuple[int, RouteRowInput, RoutingLane, PromptStage, RouteRoomModel]] = []
    for index, row in enumerate(rows):
        lane = _parse_lane(row.lane)
        stage = None if lane is None else _parse_stage(lane, row.stage)
        room_model = None if lane is None or stage is None else _parse_room_model(lane, stage, row.room_model)
        if lane is None or room_model is None or stage is None:
            errors.append(
                RouteRowError(
                    index=index,
                    rule="unknown-stage",
                    message=f"({row.lane}, {row.room_model}, {row.stage}) 는 모델 배정 표의 칸이 아니다",
                )
            )
            continue
        key = (lane, room_model, stage)
        if key in seen:
            errors.append(
                RouteRowError(index=index, rule="duplicate-row", message=f"{seen[key]}번 행과 같은 칸 {key} 이다")
            )
            continue
        seen[key] = index
        staged.append((index, row, lane, stage, room_model))

    # 물려받기는 요청 안에 그 칸의 행이 있는지로 정한다 — 값이 틀린 행이 있으면 저장 전체가 거부되므로 칸만 보면 된다.
    present = PromptRoutes({key: _placeholder_row(key) for key in seen})
    for index, row, lane, stage, room_model in staged:
        shape = _shape_problem(lane, stage, row.chain_model)
        if shape is not None:
            errors.append(RouteRowError(index=index, rule="generation-chain", message=shape))
            continue
        lane_chain = _lane_chain_problem(lane, row.chain_model)
        if lane_chain is not None:
            errors.append(RouteRowError(index=index, rule="chain-not-in-lane", message=lane_chain))
            continue
        if STAGES[stage].kind == "generation" and row.call_model != room_model:
            errors.append(
                RouteRowError(
                    index=index,
                    rule="generation-call-model",
                    message=_generation_call_model_message(lane, room_model),
                )
            )
            continue
        pair = _pair_problem(STAGES[stage].kind, row.call_model, row.backend)
        if pair is not None:
            errors.append(RouteRowError(index=index, rule="pair-not-allowed", message=pair))
            continue
        # 여기까지 온 행은 값 범위와 모양이 맞다 — 허용 목록에는 모델 축·경로 안의 값만 있다.
        parsed = parse_route_row(row)
        if parsed is None:
            raise AssertionError(f"검사를 통과한 행을 읽지 못했다: {row}")
        mismatch = _backend_problem(parsed, row_call_sites(present, parsed))
        if mismatch is not None:
            errors.append(RouteRowError(index=index, rule="backend-mismatch", message=mismatch))
            continue
        missing = missing_credentials(parsed.backend, _read_setting)
        if missing:
            errors.append(
                RouteRowError(
                    index=index,
                    rule="missing-credentials",
                    message=f"{parsed.backend} 경로의 {', '.join(missing)} 가 비어 있다",
                )
            )
            continue
        effort = _effort_problem(parsed, _read_setting)
        if effort is not None:
            errors.append(RouteRowError(index=index, rule="structured-effort", message=effort))
    return errors


def _placeholder_row(key: RouteKey) -> RouteRow:
    """칸이 있다는 표지만 하는 행 — 물려받기 판정(`row_call_sites`)은 칸의 유무만 보고 값은 읽지 않는다."""
    lane, room_model, stage = key
    return RouteRow(
        lane=lane, room_model=room_model, stage=stage, chain_model=None, call_model="gemini", backend="gemini"
    )


async def route_chain_errors(db: AsyncSession, rows: Sequence[RouteRow]) -> list[RouteRowError]:
    """저장 요청의 체인 검사(DB). 행마다 읽을 체인(생성은 방 모델·작업 모델)의 (레인, 모델) 활성 세트가 있는지(`chain-not-published`), 그
    세트가 그 단계가 읽는 채널을 다 갖는지(`chain-missing-channel`) 본다. 캐시를 쓰지 않는다 — 저장 직전에 게시된 체인을 캐시가
    아직 모를 수 있다. 같은 체인은 한 번만 읽는다. `rows` 의 위치가 오류의 `index` 다."""
    channels_by_chain: dict[tuple[RoutingLane, PromptSetModelId], frozenset[str] | None] = {}
    errors: list[RouteRowError] = []
    for index, row in enumerate(rows):
        chain = _writing_model(row.room_model, row.stage) if row.chain_model is None else row.chain_model
        key = (row.lane, chain)
        if key not in channels_by_chain:
            try:
                _, sections = await load_active_prompt_set(db, lane=row.lane, model=chain)
            except PromptSetNotFoundError:
                channels_by_chain[key] = None
            else:
                channels_by_chain[key] = frozenset(section.channel for section in sections)
        channels = channels_by_chain[key]
        if channels is None:
            errors.append(
                RouteRowError(
                    index=index,
                    rule="chain-not-published",
                    message=f"({row.lane}, {chain}) 체인에 게시된 세트가 없다",
                )
            )
            continue
        missing = [channel for channel in STAGES[row.stage].channels if channel not in channels]
        if missing:
            errors.append(
                RouteRowError(
                    index=index,
                    rule="chain-missing-channel",
                    message=f"({row.lane}, {chain}) 체인의 활성 세트에 {row.stage} 가 읽는 {', '.join(missing)} 채널이 없다",
                )
            )
    return errors
