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
from typing import Literal, get_args

from api.llm.call_policy import CALL_POLICIES, BackendId, CallKind, LLMCallSite

# 사용자가 고르는 글쓰기 모델의 id. 기동 검증이 읽어야 해서 여기 두고, `llm/chat_models.py` 가 같은 이름으로 다시 내보낸다.
ChatModelId = Literal["gemini", "sonnet", "opus"]
DEFAULT_CHAT_MODEL: ChatModelId = "gemini"


@dataclass(frozen=True, kw_only=True)
class BackendCapabilities:
    """스트리밍 생성은 모든 구현이 받는다. 구조화 출력은 구현마다 다르다 — `none` 이면 구조화 호출을 받지 못한다."""

    structured: Literal["native_schema", "none"]
    structured_images: bool
    structured_with_instruction: bool


@dataclass(frozen=True, kw_only=True)
class BackendSpec:
    capabilities: BackendCapabilities
    # 서비스하는 모델 → 그 모델의 실제 id 를 담은 `Settings` 속성 이름.
    model_id_settings: Mapping[ChatModelId, str]
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
        # Bedrock 의 Claude 는 네이티브 구조화 출력을 받지 않는다.
        capabilities=BackendCapabilities(structured="none", structured_images=False, structured_with_instruction=False),
        model_id_settings={"sonnet": "bedrock_sonnet_model_id", "opus": "bedrock_opus_model_id"},
        credential_env=(
            ("BEDROCK_ACCESS_KEY_ID", "bedrock_access_key_id"),
            ("BEDROCK_SECRET_ACCESS_KEY", "bedrock_secret_access_key"),
            ("BEDROCK_REGION", "bedrock_region"),
        ),
    ),
    "anthropic": BackendSpec(
        # 직접 API 는 JSON 스키마 출력을 받지만, 이 구현은 아직 구조화 호출을 구현하지 않았다.
        capabilities=BackendCapabilities(structured="none", structured_images=False, structured_with_instruction=False),
        model_id_settings={"sonnet": "anthropic_sonnet_model_id", "opus": "anthropic_opus_model_id"},
        credential_env=(("ANTHROPIC_DIRECT_API_KEY", "anthropic_direct_api_key"),),
    ),
}

# 모델 → 그 모델을 서비스할 수 있는 구현, 첫 값이 기본(배정이 없을 때 가는 곳). 서비스 여부 자체는 위 행의
# `model_id_settings` 에도 있어 이 표는 "기본 순서" 만의 소스다 — 두 표가 같은 사실을 말하는지는 테스트가 본다.
MODEL_BACKENDS: dict[ChatModelId, tuple[BackendId, ...]] = {
    "gemini": ("gemini",),
    "sonnet": ("bedrock", "anthropic"),
    "opus": ("bedrock", "anthropic"),
}


def pick_backend(
    call_site: LLMCallSite, model: ChatModelId, assignments: Mapping[LLMCallSite, BackendId]
) -> tuple[ChatModelId, BackendId]:
    """호출 하나의 (모델, 구현). 순수하다 — 경고는 돌려받은 모델이 넘긴 모델과 다른지 보고 호출부가 남긴다.

    1. 모델을 고를 수 없는 호출에 기본 아닌 모델이 실려 오면 기본 모델로 읽는다. 사용자가 고른 적 없는 호출에 비싼
       모델 원가가 붙지 않게 한다.
    2. 배정은 `assignments`(env), 없으면 정책 표 행의 `backend`.
    3. 배정된 구현이 그 모델을 서비스하면 배정을, 아니면 그 모델의 기본 구현을 쓴다."""
    policy = CALL_POLICIES[call_site]
    if model != DEFAULT_CHAT_MODEL and not policy.model_selectable:
        model = DEFAULT_CHAT_MODEL
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


def assignment_errors(assignments: Mapping[LLMCallSite, BackendId], read_setting: Callable[[str], str]) -> list[str]:
    """env 배정이 기동해도 되는지. 문제마다 한 줄을 돌려주고, 비어 있으면 통과다. `read_setting` 은 `Settings` 속성
    이름으로 값을 읽는다(검증자가 자기 자신에서 읽게 넘긴다).

    - 그 호출의 모델(모델을 고르는 호출이면 전부, 아니면 기본 모델) 중 하나도 서비스하지 못하는 구현은 거부한다 — 해석
      규칙이 조용히 무시해 배정이 아무 일도 하지 않는다.
    - 그 호출의 방식을 받지 못하는 구현은 거부한다 — 첫 호출에서야 실패한다.
    - 배정이 어떤 모델의 경로를 기본 구현에서 옮기는데 그 구현의 자격이 비어 있으면 거부한다. 기본 구현을 그대로 적은
      배정은 경로를 바꾸지 않으므로 자격을 묻지 않는다."""
    errors: list[str] = []
    for call_site, backend in assignments.items():
        policy = CALL_POLICIES[call_site]
        spec = BACKENDS[backend]
        models: tuple[ChatModelId, ...] = get_args(ChatModelId) if policy.model_selectable else (DEFAULT_CHAT_MODEL,)
        served = [model for model in models if model in spec.model_id_settings]
        entry = f"LLM_CALL_SITE_BACKENDS 의 {call_site}:{backend}"
        if not served:
            errors.append(f"{entry} — {backend} 는 이 호출의 모델({', '.join(models)})을 하나도 서비스하지 않는다")
            continue
        if not _takes(spec.capabilities, policy.call_kind):
            errors.append(f"{entry} — {backend} 는 이 호출의 방식({policy.call_kind})을 받지 못한다")
            continue
        if all(MODEL_BACKENDS[model][0] == backend for model in served):
            continue
        missing = [env_name for env_name, attr in spec.credential_env if not read_setting(attr).strip()]
        if missing:
            errors.append(f"{entry} — 경로를 {backend} 로 옮기는데 {', '.join(missing)} 가 비어 있다")
    return errors
