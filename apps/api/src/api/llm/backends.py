"""공급자 구현 등록부. 구현마다 무엇을 받을 수 있고(능력), 어느 모델을 어느 설정의 id 로 서비스하고, 경로를 넘겨받을 때
어떤 자격이 있어야 하는지를 한 행에 적는다. 호출 하나가 어느 구현으로 가는지 정하는 순수 규칙(`pick_backend`)과 env 배정의
기동 검증 규칙(`assignment_errors`)도 여기 둔다.

잎 모듈이다 — `core/config.py` 의 `Settings` 검증자가 이 모듈을 읽는데, `settings = Settings()` 는 `core/config.py` 를
import 하는 도중에 돈다. 여기서 `settings` 나 그것을 import 하는 모듈을 부르면 설정을 만드는 도중에 설정을 찾다 기동이
`ImportError` 로 깨진다. 그래서 표에는 설정 값이 아니라 설정 **이름**만 담고, 실제 id 를 읽는 일은 `llm/chat_models.py` 의
`backend_model_id`, 구현을 만드는 일은 `llm/routing.py` 의 팩토리 사전이 맡는다. 함수는 표를 호출할 때마다 이 모듈의
이름으로 읽는다(테스트가 표에 행을 더하면 검증과 해석에 그대로 실린다).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, TypeGuard, get_args

from api.llm.call_policy import CALL_POLICIES, BackendId, CallKind, LLMCallSite

# 사용자가 고르는 글쓰기 모델의 id. 기동 검증이 읽어야 해서 여기 두고, `llm/chat_models.py` 가 같은 이름으로 다시 내보낸다.
ChatModelId = Literal["gemini", "sonnet", "opus"]
DEFAULT_CHAT_MODEL: ChatModelId = "gemini"
# 프롬프트 세트 체인의 모델 축이자 판정·요약 모델 설정의 값 — 글쓰기 모델 전부에 판정 전용 id(`haiku`)를 더한 것이다. 판정
# 전용 id 로는 글을 쓰지 않으므로 글쓰기 모델 타입·채팅 선택에는 넣지 않는다. 기동 검증이 판정 모델 설정을 읽어야 해서 여기 두고,
# `llm/chat_models.py` 가 같은 이름으로 다시 내보낸다.
PromptSetModelId = Literal["gemini", "sonnet", "opus", "haiku"]
_PROMPT_SET_MODEL_IDS: frozenset[str] = frozenset(get_args(PromptSetModelId))


@dataclass(frozen=True, kw_only=True)
class BackendCapabilities:
    """스트리밍 생성은 모든 구현이 받는다. 구조화 출력은 구현마다 다르다 — `none` 이면 구조화 호출을 받지 못한다.
    `native_schema` 는 SDK 가 응답 스키마를 직접 받는 Gemini, `json_schema` 는 Messages API 의 `output_config.format`(JSON
    스키마)으로 받는 Claude 다."""

    structured: Literal["native_schema", "json_schema", "none"]
    structured_images: bool
    structured_with_instruction: bool


@dataclass(frozen=True, kw_only=True)
class BackendSpec:
    capabilities: BackendCapabilities
    # 서비스하는 모델 → 그 모델의 실제 id 를 담은 `Settings` 속성 이름.
    model_id_settings: Mapping[PromptSetModelId, str]
    # (env 이름, `Settings` 속성 이름). 배정이 이 구현으로 경로를 옮길 때 비어 있으면 기동하지 않는다.
    credential_env: tuple[tuple[str, str], ...]


BACKENDS: dict[BackendId, BackendSpec] = {
    "gemini": BackendSpec(
        capabilities=BackendCapabilities(
            structured="native_schema", structured_images=True, structured_with_instruction=True
        ),
        model_id_settings={"gemini": "gemini_model_name"},
        # Gemini 가 서비스하는 모델은 Gemini 가 기본 구현인 모델뿐이라, 배정이 경로를 Gemini 로 옮겨 오는 일이 없다.
        credential_env=(),
    ),
    "bedrock": BackendSpec(
        # 구조화 출력은 Claude 공용 조각(`llm/claude_messages.py`)으로 받는다. 그림을 싣거나 지시문을 따로 싣는 구조화(발행
        # 심사·소설화)는 구현하지 않았다.
        capabilities=BackendCapabilities(
            structured="json_schema", structured_images=False, structured_with_instruction=False
        ),
        model_id_settings={
            "sonnet": "bedrock_sonnet_model_id",
            "opus": "bedrock_opus_model_id",
            "haiku": "bedrock_haiku_model_id",
        },
        credential_env=(
            ("BEDROCK_ACCESS_KEY_ID", "bedrock_access_key_id"),
            ("BEDROCK_SECRET_ACCESS_KEY", "bedrock_secret_access_key"),
            ("BEDROCK_REGION", "bedrock_region"),
        ),
    ),
    "anthropic": BackendSpec(
        # Bedrock 과 같은 공용 조각으로 같은 구조화 호출만 받는다.
        capabilities=BackendCapabilities(
            structured="json_schema", structured_images=False, structured_with_instruction=False
        ),
        model_id_settings={
            "sonnet": "anthropic_sonnet_model_id",
            "opus": "anthropic_opus_model_id",
            "haiku": "anthropic_haiku_model_id",
        },
        credential_env=(("ANTHROPIC_DIRECT_API_KEY", "anthropic_direct_api_key"),),
    ),
}

# 모델 → 그 모델을 서비스할 수 있는 구현, 첫 값이 기본(배정이 없을 때 가는 곳). 서비스 여부 자체는 위 행의
# `model_id_settings` 에도 있어 이 표는 "기본 순서" 만의 소스다 — 두 표가 같은 사실을 말하는지는 테스트가 본다.
# 판정 전용 `haiku` 도 여기 있다 — 판정 모델로 고를 수 있어야 해서다. 그래서 이 표의 키는 "글쓰기 모델"이 아니다. 상위
# 글쓰기 모델을 따지는 곳(상위 모델 스위치의 기동 검증)은 이 표가 아니라 `ChatModelId` 를 본다.
MODEL_BACKENDS: dict[PromptSetModelId, tuple[BackendId, ...]] = {
    "gemini": ("gemini",),
    "sonnet": ("bedrock", "anthropic"),
    "opus": ("bedrock", "anthropic"),
    "haiku": ("bedrock", "anthropic"),
}


def call_site_model(call_site: LLMCallSite, read_setting: Callable[[str], str]) -> PromptSetModelId:
    """모델을 설정으로 고르는 호출(판정·요약)이면 그 설정의 모델, 아니면 기본 모델. 구조화 호출의 라우팅, Claude 구현이 보낼
    모델 id, 판정 덤프, 판정 세트 읽기, 기동 검증이 모두 이 함수 하나로 모델을 정한다 — 따로 계산하면 덤프의 id 나 읽은
    세트가 실제로 보낸 모델과 어긋난다. `read_setting` 은 `Settings` 속성 이름으로 값을 읽는다(설정은 검증된 값이라 모델 축
    밖이면 읽는 쪽의 버그다)."""
    name = CALL_POLICIES[call_site].model_setting
    if name is None:
        return DEFAULT_CHAT_MODEL
    value = read_setting(name)
    if not _is_prompt_set_model_id(value):
        raise ValueError(f"{name} 의 값 {value!r} 은 문안 체인의 모델 id 가 아니다")
    return value


def _is_prompt_set_model_id(value: str) -> TypeGuard[PromptSetModelId]:
    return value in _PROMPT_SET_MODEL_IDS


def pick_backend(
    call_site: LLMCallSite,
    model: PromptSetModelId,
    assignments: Mapping[LLMCallSite, BackendId],
    *,
    call_model: PromptSetModelId = DEFAULT_CHAT_MODEL,
) -> tuple[PromptSetModelId, BackendId]:
    """호출 하나의 (모델, 구현). 순수하다 — 경고는 돌려받은 모델이 넘긴 모델과 다른지 보고 호출부가 남긴다.

    1. 모델을 고를 수 없는 호출에 다른 모델이 실려 오면 그 호출의 모델(`call_model`)로 읽는다. 사용자가 고른 적 없는 호출에
       방의 비싼 모델 원가가 붙지 않게 한다. 그 호출의 모델은 판정·요약이면 그 설정의 모델이고 나머지는 기본 모델이다 —
       설정을 읽는 것은 부르는 쪽이다(`call_site_model`, 이 함수는 순수하게 둔다).
    2. 배정은 `assignments`(env), 없으면 정책 표 행의 `backend`.
    3. 배정된 구현이 그 모델을 서비스하면 배정을, 아니면 그 모델의 기본 구현을 쓴다."""
    policy = CALL_POLICIES[call_site]
    if model != call_model and not policy.model_selectable:
        model = call_model
    assigned = assignments.get(call_site, policy.backend)
    if assigned is not None and model in BACKENDS[assigned].model_id_settings:
        return model, assigned
    return model, MODEL_BACKENDS[model][0]


def _takes(capabilities: BackendCapabilities, kind: CallKind) -> bool:
    if kind == "stream":
        return True
    if capabilities.structured == "none":
        return False
    if kind == "structured_images":
        return capabilities.structured_images
    if kind == "structured_with_instruction":
        return capabilities.structured_with_instruction
    return True


def _missing_credentials(backend: BackendId, read_setting: Callable[[str], str]) -> list[str]:
    return [env_name for env_name, attr in BACKENDS[backend].credential_env if not read_setting(attr).strip()]


def assignment_errors(assignments: Mapping[LLMCallSite, BackendId], read_setting: Callable[[str], str]) -> list[str]:
    """env 배정과 판정·요약 모델 설정이 기동해도 되는지. 문제마다 한 줄을 돌려주고, 비어 있으면 통과다. `read_setting` 은
    `Settings` 속성 이름으로 값을 읽는다(검증자가 자기 자신에서 읽게 넘긴다).

    배정마다:
    - 그 호출의 모델(모델을 고르는 호출이면 전부, 모델 설정이 있는 호출이면 그 설정의 모델, 아니면 기본 모델) 중 하나도
      서비스하지 못하는 구현은 거부한다 — 해석 규칙이 조용히 무시해 배정이 아무 일도 하지 않는다. 판정 모델이 `haiku` 인데
      배정이 `gemini` 면 판정은 조용히 Bedrock 으로 간다.
    - 그 호출의 방식을 받지 못하는 구현은 거부한다 — 첫 호출에서야 실패한다.
    - 배정이 어떤 모델의 경로를 기본 구현에서 옮기는데 그 구현의 자격이 비어 있으면 거부한다. 기본 구현을 그대로 적은
      배정은 경로를 바꾸지 않으므로 자격을 묻지 않는다.

    모델 설정이 있는 호출(판정·요약)은 배정이 있든 없든 그 호출이 실제로 갈 구현을 해석해, 방식을 받지 못하거나 자격이 비어
    있으면 거부한다 — 판정 모델만 바꾸고 배정을 두지 않으면 판정은 그 모델의 기본 구현(Claude 면 Bedrock)으로 가는데, 그
    자격이 비어 있으면 매 판정이 실패한다. 채팅 판정과 미리보기 판정은 모델 설정을 함께 쓰지만 배정은 호출 위치마다라
    따로 본다."""
    errors: list[str] = []
    for call_site, backend in assignments.items():
        policy = CALL_POLICIES[call_site]
        spec = BACKENDS[backend]
        models: tuple[PromptSetModelId, ...]
        if policy.model_selectable:
            models = get_args(ChatModelId)
        else:
            models = (call_site_model(call_site, read_setting),)
        served = [model for model in models if model in spec.model_id_settings]
        entry = f"LLM_CALL_SITE_BACKENDS 의 {call_site}:{backend}"
        if not served:
            errors.append(f"{entry} — {backend} 는 이 호출의 모델({', '.join(models)})을 하나도 서비스하지 않는다")
            continue
        if policy.model_setting is not None:
            # 방식과 자격은 아래에서 배정 없는 경우와 함께 본다.
            continue
        if not _takes(spec.capabilities, policy.call_kind):
            errors.append(f"{entry} — {backend} 는 이 호출의 방식({policy.call_kind})을 받지 못한다")
            continue
        if all(MODEL_BACKENDS[model][0] == backend for model in served):
            continue
        missing = _missing_credentials(backend, read_setting)
        if missing:
            errors.append(f"{entry} — 경로를 {backend} 로 옮기는데 {', '.join(missing)} 가 비어 있다")
    for call_site, policy in CALL_POLICIES.items():
        if policy.model_setting is None:
            continue
        model = call_site_model(call_site, read_setting)
        _, backend = pick_backend(call_site, model, assignments, call_model=model)
        entry = f"{policy.model_setting} 가 {model} 인 {call_site}"
        if not _takes(BACKENDS[backend].capabilities, policy.call_kind):
            errors.append(f"{entry} — 가는 구현 {backend} 는 이 호출의 방식({policy.call_kind})을 받지 못한다")
            continue
        missing = _missing_credentials(backend, read_setting)
        if missing:
            errors.append(f"{entry} — 가는 구현 {backend} 의 {', '.join(missing)} 가 비어 있다")
    return errors
