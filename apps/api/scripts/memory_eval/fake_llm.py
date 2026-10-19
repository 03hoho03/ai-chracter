"""유료 호출 없이 하네스 절차를 끝까지 돌려 보는 가짜 LLM 클라이언트. 요약 호출에 결정론적인 짧은 요약을 돌려준다.

요약 품질은 의미가 없다 — 접기·스냅샷·되감기·얼리기·복원 절차가 실제 앱 함수 위에서 맞게 도는지만 본다."""

import hashlib
from collections.abc import AsyncIterator
from typing import TypeVar

from pydantic import BaseModel

from api.chat.prompt_builder import MemorySummaryResult
from api.llm.client import LLMCallContext, LLMClient

T = TypeVar("T", bound=BaseModel)


class FakeMemoryLLM(LLMClient):
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise RuntimeError("하네스 가짜 클라이언트는 생성을 하지 않는다")
        yield ""  # pragma: no cover

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        images: list[tuple[bytes, str]] | None = None,
        *,
        usage: LLMCallContext,
    ) -> T:
        self.calls.append(usage.call_site)
        if response_schema is MemorySummaryResult:
            digest = hashlib.sha256(prompt.encode()).hexdigest()[:8]
            return response_schema.model_validate(
                {"summary": f"[가짜 요약 {len(self.calls)} · {digest}] 접힌 대화 {len(prompt)}자"}
            )
        if set(response_schema.model_fields) == {"episodes"}:
            # 에피소드 추출 결과 — 빈 목록도 정상 결과다(장면 0개).
            return response_schema.model_validate({"episodes": []})
        if set(response_schema.model_fields) == {"facts"}:
            # 사실 추출 결과 — 빈 목록도 정상 결과다(사실 0개).
            return response_schema.model_validate({"facts": []})
        raise RuntimeError(f"하네스 가짜 클라이언트가 모르는 결과 스키마: {response_schema.__name__}")
