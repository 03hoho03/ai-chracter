import abc
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# `gemini_usage` 로그의 grep 키다. 호출부와 1:1이라
# 값을 바꾸거나 합치면 로그 분포가 끊긴다. 재생성은 `chat_generate`로 함께 집계한다.
LLMCallSite = Literal[
    "chat_generate",
    "chat_stat_judgment",
    "chat_ending_judgment",
    "chat_situational_image",
    # 스토리 미디어 북 칸 판정. 재생성도 여기로 함께 집계한다(생성과 같은 규칙).
    "chat_media_book_image",
    "chat_memory_summary",
    "preview_generate",
    "preview_stat_judgment",
    "preview_ending_judgment",
    "preview_media_book_image",
    "publish_filter_character",
    "publish_filter_story",
    "seed_story_generate",
    "seed_similarity_review",
]

# 아래 두 집합은 로그 라벨이면서 **모델·사고 설정 선택도 겸한다** — `llm/gemini.py` 의
# `generate_structured` 가 이 집합으로 `gemini_judgment_*`·`gemini_publish_filter_*` 설정을 고른다.
# 그래서 call_site 를 새로 만들거나 합치거나 나누면 그 호출이 어느 모델로 가는지도 바뀐다.
# 새 판정·심사 call_site 는 여기에 넣어야 스위치를 따라가고, 빠뜨리면 조용히 기본 모델로 돈다.
# 기억 요약(`chat_memory_summary`)은 매 턴 생성 프롬프트에 실려 생성 품질에 바로 닿고, 시드
# 스크립트 호출은 운영 판정이 아니라서 둘 다 넣지 않는다.
JUDGMENT_CALL_SITES: frozenset[LLMCallSite] = frozenset(
    {
        "chat_stat_judgment",
        "chat_ending_judgment",
        "chat_situational_image",
        "chat_media_book_image",
        "preview_stat_judgment",
        "preview_ending_judgment",
        "preview_media_book_image",
    }
)
# 발행 심사는 실패하면 발행이 막히는(fail-closed) 경로라 판정과 따로 바꾸고 되돌릴 수 있게 둔다.
PUBLISH_FILTER_CALL_SITES: frozenset[LLMCallSite] = frozenset(
    {"publish_filter_character", "publish_filter_story"}
)


@dataclass(frozen=True)
class LLMCallContext:
    """호출 한 건의 사용량을 누구·어디에 귀속할지. 필수 키워드 인자라 새 호출부가
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

    `llm/gemini.py`가 네트워크 타임아웃(`httpx.HTTPError`)과
    쿼터 소진(`genai_errors.APIError(code=429)`)을 구분하려고 두는 서브클래스다 — 여전히
    `LLMClientError`라 기존 `except LLMClientError`가 그대로 잡으므로 사용자에게 보이는
    동작(흡수)은 바뀌지 않는다. 호출부는 `isinstance` 검사로 승격 이벤트의 태그만 갈라 붙인다."""


class LLMClient(abc.ABC):
    """Provider-agnostic 대화 생성/판단 인터페이스.

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
        """`stop_sequences`는 호출부가 넘긴다 — 대본 프레임의
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
        자동 필터)에 프롬프트와 함께 첨부된다."""
        raise NotImplementedError
