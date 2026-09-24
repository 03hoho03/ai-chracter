import abc
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# backlog-sweep-goal-prompt.md BS-18·BS-21: `gemini_usage` 로그의 grep 키다. 호출부와 1:1이라
# 값을 바꾸거나 합치면 로그 분포가 끊긴다. 재생성은 `chat_generate`로 함께 집계한다(BS-21).
LLMCallSite = Literal[
    "chat_generate",
    "chat_stat_judgment",
    "chat_ending_judgment",
    "chat_situational_image",
    "preview_generate",
    "preview_stat_judgment",
    "preview_ending_judgment",
    "publish_filter_character",
    "publish_filter_story",
    "seed_story_generate",
    "seed_similarity_review",
]


@dataclass(frozen=True)
class LLMCallContext:
    """호출 한 건의 사용량을 누구·어디에 귀속할지(BS-19). 필수 키워드 인자라 새 호출부가
    빠뜨리면 mypy가 잡는다. `room_id`는 DB 방이 없는 호출(미리보기·발행 심사·스크립트)에서 None."""

    call_site: LLMCallSite
    user_id: uuid.UUID | None
    room_id: uuid.UUID | None


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
        *,
        usage: LLMCallContext,
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
        *,
        usage: LLMCallContext,
    ) -> T:
        """`images`는 (바이트, MIME 타입) 쌍의 목록 — 전달되면 멀티모달 판단(예: 발행
        자동 필터, techspec-backend-content.md §1.3)에 프롬프트와 함께 첨부된다."""
        raise NotImplementedError
