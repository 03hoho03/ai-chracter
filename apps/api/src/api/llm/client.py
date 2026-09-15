import abc
from collections.abc import AsyncIterator
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClientError(Exception):
    """Raised when an LLM provider call fails or returns an unusable response."""


class LLMPolicyViolationError(LLMClientError):
    """Raised when the provider's safety filtering blocks a prompt or its output."""


class LLMRateLimitError(LLMClientError):
    """Raised when the provider reports quota exhaustion (HTTP 429).

    monitoring-techspec.md MT-6: `llm/gemini.py`가 네트워크 타임아웃(`httpx.HTTPError`)과
    쿼터 소진(`genai_errors.APIError(code=429)`)을 구분하려고 두는 서브클래스다 — 여전히
    `LLMClientError`라 기존 `except LLMClientError`가 그대로 잡으므로 사용자에게 보이는
    동작(흡수)은 바뀌지 않는다. 호출부는 `isinstance` 검사로 승격 이벤트의 태그만 갈라 붙인다."""


class LLMClient(abc.ABC):
    """Provider-agnostic 대화 생성/판단 인터페이스 (techspec-overview-backend.md §5).

    generate()는 대화 생성 전용 스트리밍, generate_structured()는 판단
    (엔딩판정/스탯증감/이미지매칭) 전용이며 자유텍스트 파싱 없이 지정된
    Pydantic 모델로 역직렬화된 결과를 반환한다.
    """

    @abc.abstractmethod
    def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
    ) -> AsyncIterator[str]:
        """`stop_sequences`는 호출부가 넘긴다 — prompt-db-goal-prompt.md §4-5: 대본 프레임의
        화자 라벨(`{user_label}:`)에서 파생된 값이라 라벨과 정지 시퀀스가 따로 편집될 수
        없다(어긋나면 모델이 사용자 턴까지 지어낸다)."""
        raise NotImplementedError

    @abc.abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        images: list[tuple[bytes, str]] | None = None,
    ) -> T:
        """`images`는 (바이트, MIME 타입) 쌍의 목록 — 전달되면 멀티모달 판단(예: 발행
        자동 필터, techspec-backend-content.md §1.3)에 프롬프트와 함께 첨부된다."""
        raise NotImplementedError
