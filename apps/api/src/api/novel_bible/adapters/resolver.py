"""실제 모델 어댑터와 연산 → 어댑터 해석기. 코어는 `BibleModelAdapter` 계약만 알고, 바깥 입구가 이 해석기를 만들어 넘긴다.

어댑터는 코드 표의 스펙 한 행이다 — 문안은 그 체인의 활성 novel 레인 세트를 읽고, 호출은 지시문을 따로 싣는 구조화 하나로 그 연산의
호출 위치에 부를 모델(`call_model`)을 실어 보낸다. 스트림은 쓰지 않는다 — Claude 구현의 스트림은 호출 문맥의 글쓰기 모델 칸
(`LLMCallContext.model`)으로 id 를 골라, 그 칸에 실을 수 없는 판정 전용 모델(haiku)로는 부를 수 없다."""

from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import PromptSetNotFoundError, load_active_prompt_set
from api.core.config import settings
from api.llm.call_failures import classify_llm_failure
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, LLMRateLimitError
from api.llm.dependencies import get_llm_client
from api.novel_bible.adapters.records import recorded_bible_call
from api.novel_bible.adapters.table import ADAPTERS, OPERATION_CALL_SITES, AdapterId, effective_adapters
from api.novel_bible.core.contracts import AdapterCallError, AdapterCapabilities, AdapterResolver, PromptSource
from api.novel_bible.core.types import RenderedPrompt
from api.novel_bible.ids import OperationKey

T = TypeVar("T", bound=BaseModel)


class ModelAdapter:
    """코드 표의 어댑터 하나. 클라이언트를 받지 않으면 부를 때 앱의 클라이언트(`get_llm_client`)를 얻는다 — 해석기를 만드는 것만으로
    Gemini 키를 요구하지 않게 한다(확정 입구는 문안만 읽는다)."""

    def __init__(self, adapter_id: AdapterId, llm_client: LLMClient | None = None) -> None:
        self._spec = ADAPTERS[adapter_id]
        self._llm_client = llm_client
        self.id: str = adapter_id
        self.capabilities = AdapterCapabilities(
            structured=self._spec.structured,
            with_instruction=self._spec.with_instruction,
            max_input_chars=self._spec.max_input_chars,
        )

    async def prompt_source(self, session: AsyncSession) -> PromptSource:
        """체인에 활성 세트가 없으면 다시 불러도 같으므로 재시도하지 않는 `prompt_missing` 이다."""
        try:
            prompt_set, sections = await load_active_prompt_set(session, lane="novel", model=self._spec.prompt_chain)
        except PromptSetNotFoundError as error:
            raise AdapterCallError("prompt_missing", retryable=False) from error
        return PromptSource(prompt_set_id=prompt_set.id, sections=sections)

    async def structured(
        self, prompt: RenderedPrompt, schema: type[T], *, records: list[dict[str, Any]], stage: OperationKey
    ) -> T:
        """사용자 귀속이 없는 내부 호출이다. 공급자 예외는 코어가 아는 실패 사유로 바꿔 올린다 — 안전 차단만 다시 불러도 같아
        재시도하지 않는다."""
        usage = LLMCallContext(
            call_site=OPERATION_CALL_SITES[stage], user_id=None, room_id=None, call_model=self._spec.call_model
        )
        client = self._llm_client or get_llm_client()
        try:
            with recorded_bible_call(records, usage, stage=stage, prompt_set_id=prompt.prompt_set_id) as recorded:
                return await client.generate_structured_with_instruction(
                    prompt.prompt, schema, system_instruction=prompt.system_instruction, usage=recorded
                )
        except LLMRateLimitError as error:
            raise AdapterCallError("rate_limited", retryable=True) from error
        except LLMClientError as error:
            code = classify_llm_failure(error)
            raise AdapterCallError(code, retryable=code != "blocked") from error


def build_resolver(llm_client: LLMClient | None = None) -> AdapterResolver:
    """연산 → 어댑터. 코드 표에 env 덮어쓰기(`novel_bible_adapters`)를 얹은 배정을 만들 때 한 번 읽는다. 같은 어댑터에 배정된 연산은
    같은 객체를 받는다."""
    assigned = effective_adapters(settings.novel_bible_adapters)
    adapters = {adapter_id: ModelAdapter(adapter_id, llm_client) for adapter_id in set(assigned.values())}
    return lambda operation: adapters[assigned[operation]]
