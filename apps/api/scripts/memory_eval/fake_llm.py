"""유료 호출 없이 하네스 절차를 끝까지 돌려 보는 가짜 LLM 클라이언트. 요약 호출에 결정론적인 짧은 요약을 돌려준다.

요약 품질은 의미가 없다 — 접기·스냅샷·되감기·얼리기·복원 절차가 실제 앱 함수 위에서 맞게 도는지만 본다. 턴 판정(장면·스탯 규칙·
엔딩·상황 이미지)은 "바뀐 것 없음" 결과를 돌려준다 — 앱이 턴마다 구조화 호출로 부르는 스키마를 모르는 스키마로 거부하면 가짜
경로에서 턴 판정이 불리는 순간 절차가 깨진다."""

import hashlib
from collections.abc import AsyncIterator
from typing import TypeVar

from pydantic import BaseModel

from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    MemorySummaryResult,
    SceneJudgmentResult,
    StatRuleJudgmentResult,
)
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
        if response_schema is SceneJudgmentResult:
            # 근거 없는 칸은 null — 앱은 직전 장면을 이어받는다.
            return response_schema.model_validate({"place": None, "time": None})
        if response_schema is StatRuleJudgmentResult:
            return response_schema.model_validate({"fired_rule_ids": []})
        if response_schema is EndingJudgmentResult:
            return response_schema.model_validate({"triggered": False})
        if response_schema is ImageMatchJudgmentResult:
            return response_schema.model_validate({"matched_image_entity_id": None})
        if set(response_schema.model_fields) == {"episodes"}:
            # 에피소드 추출 결과 — 빈 목록도 정상 결과다(장면 0개).
            return response_schema.model_validate({"episodes": []})
        if set(response_schema.model_fields) == {"facts"}:
            # 사실 추출 결과 — 빈 목록도 정상 결과다(사실 0개).
            return response_schema.model_validate({"facts": []})
        raise RuntimeError(f"하네스 가짜 클라이언트가 모르는 결과 스키마: {response_schema.__name__}")
