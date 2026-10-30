"""정본 기억의 어댑터 코드 표와 그 기동 검증. 설정의 검증자가 읽으므로 잎 모듈이다 — `llm/backends.py`·`llm/call_policy.py`·
`novel_bible/ids.py` 밖의 앱 모듈을 import 하지 않는다(설정을 만드는 도중에 다른 모듈을 끌어오면 기동이 깨진다).

어댑터는 (부를 모델, 읽을 소설 레인 문안 체인) 한 쌍이다. 연산(슬롯 추출·충돌 판정)마다 어느 어댑터를 쓸지 이 표가 정하고, env
`NOVEL_BIBLE_ADAPTERS` 가 연산별로 덮어쓴다. 처음 표는 Gemini 어댑터 하나다."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from api.llm.backends import (
    BACKENDS,
    NOVEL_MODELS,
    PromptSetModelId,
    missing_credentials,
    pick_backend,
    structured_effort_error,
)
from api.llm.call_policy import BackendId, LLMCallSite
from api.novel_bible.ids import OperationKey

AdapterId = Literal["gemini"]

# novel 레인에 있는 체인 — 어드민 문안 화면의 레인 규칙(`admin/prompts.py` 의 `_require_lane_model`)과 같은 집합이다. 판정 전용
# 체인(haiku)과 채팅 전용 글쓰기 체인(haiku_writer)은 소설 레인에 없어, 글쓰기 모델 전부가 아니라 소설에서 고를 수 있는 모델이다.
# 두 곳이 같은 사실을 말하는지는 테스트가 본다.
NOVEL_LANE_CHAINS: frozenset[PromptSetModelId] = frozenset(NOVEL_MODELS)

# 정본 기억 호출은 어느 구현으로 가든 이 키를 전제로 한다 — 어댑터는 주입받은 클라이언트가 없으면 앱의 모델 클라이언트
# (`get_llm_client`)를 쓰는데, 그 클라이언트는 어느 구현으로 보내든 Gemini 클라이언트를 먼저 만들고 키가 비면 거기서 실패한다.
# 등록부의 Gemini 행은 자격을 적지 않으므로(배정이 경로를 Gemini 로 옮겨 오는 일이 없어서다) 배정과 무관하게 따로 한 번 본다.
_GEMINI_KEY = ("GEMINI_API_KEY", "gemini_api_key")


@dataclass(frozen=True, kw_only=True)
class AdapterSpec:
    call_model: PromptSetModelId  # 부를 모델 — 호출 문맥의 `call_model` 로 싣는다
    prompt_chain: PromptSetModelId  # 읽을 novel 레인 체인
    structured: bool
    with_instruction: bool
    max_input_chars: int  # 지시문과 본문을 합친 글자 수 상한 — 넘으면 부르지 않고 작업을 실패로 끝낸다


ADAPTERS: dict[AdapterId, AdapterSpec] = {
    "gemini": AdapterSpec(
        call_model="gemini", prompt_chain="gemini", structured=True, with_instruction=True, max_input_chars=200_000
    ),
}

SLOT_OPERATION_ADAPTERS: dict[OperationKey, AdapterId] = {
    "events.extract": "gemini",
    "facts.extract": "gemini",
    "knowledge.extract": "gemini",
    "conflicts.judge": "gemini",
}

OPERATION_CALL_SITES: dict[OperationKey, LLMCallSite] = {
    "events.extract": "novel_bible_extract_events",
    "facts.extract": "novel_bible_extract_facts",
    "knowledge.extract": "novel_bible_extract_knowledge",
    "conflicts.judge": "novel_bible_judge",
}


def effective_adapters(overrides: Mapping[OperationKey, AdapterId]) -> dict[OperationKey, AdapterId]:
    """연산마다 쓸 어댑터 — 코드 표 위에 env 덮어쓰기를 얹는다."""
    return {**SLOT_OPERATION_ADAPTERS, **overrides}


def adapter_errors(
    overrides: Mapping[OperationKey, AdapterId],
    assignments: Mapping[LLMCallSite, BackendId],
    read_setting: Callable[[str], str],
) -> list[str]:
    """켜진 스위치로 뜰 때 연산의 배정마다: 어댑터의 구조화 능력과 지시문 분리 능력, 문안 체인이 novel 레인에 있는지, 그 호출이
    실제로 갈 구현(`pick_backend`)이 지시문을 따로 싣는 구조화를 받는지, 그 구현의 자격(`missing_credentials`)과 구조화
    깊이(`structured_effort_error`). Gemini 키는 배정과 무관하게 그 앞에서 한 번 본다. 문제마다 한 줄을 돌려주고, 비어 있으면
    통과다. `read_setting` 은 `Settings` 속성 이름으로 값을 읽는다."""
    errors: list[str] = []
    if not read_setting(_GEMINI_KEY[1]).strip():
        errors.append(
            f"정본 기억 호출은 어느 구현으로 가든 Gemini 클라이언트를 먼저 만드는데 {_GEMINI_KEY[0]} 가 비어 있다"
        )
    for operation, adapter_id in effective_adapters(overrides).items():
        spec = ADAPTERS[adapter_id]
        call_site = OPERATION_CALL_SITES[operation]
        if not (spec.structured and spec.with_instruction):
            errors.append(f"{operation} 에 배정한 {adapter_id} 는 지시문을 따로 싣는 구조화 출력을 하지 못한다")
        if spec.prompt_chain not in NOVEL_LANE_CHAINS:
            errors.append(f"{adapter_id} 가 읽을 체인 {spec.prompt_chain} 은 소설 레인에 없다")
        model, backend = pick_backend(call_site, spec.call_model, assignments, call_model=spec.call_model)
        capabilities = BACKENDS[backend].capabilities
        if capabilities.structured == "none" or not capabilities.structured_with_instruction:
            errors.append(f"{operation} 이 가는 구현 {backend} 는 지시문을 따로 싣는 구조화 호출을 받지 못한다")
        missing = missing_credentials(backend, read_setting)
        if missing:
            errors.append(f"{operation} 이 가는 구현 {backend} 의 {', '.join(missing)} 가 비어 있다")
        effort = structured_effort_error(backend, model, read_setting)
        if effort is not None:
            errors.append(f"{operation} — {effort}")
    return errors
