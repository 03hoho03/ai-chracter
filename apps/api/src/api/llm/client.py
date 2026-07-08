import abc
from collections.abc import AsyncIterator
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClientError(Exception):
    """Raised when an LLM provider call fails or returns an unusable response."""


class LLMPolicyViolationError(LLMClientError):
    """Raised when the provider's safety filtering blocks a prompt or its output."""


class LLMClient(abc.ABC):
    """Provider-agnostic 대화 생성/판단 인터페이스 (techspec-overview-backend.md §5).

    generate()는 대화 생성 전용 스트리밍, generate_structured()는 판단
    (엔딩판정/스탯증감/이미지매칭) 전용이며 자유텍스트 파싱 없이 지정된
    Pydantic 모델로 역직렬화된 결과를 반환한다.
    """

    @abc.abstractmethod
    def generate(self, prompt: str) -> AsyncIterator[str]:
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
