import abc
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel

from api.core.config import settings

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

# 아래 집합들은 로그 라벨이면서 **모델 선택도 겸한다** — `llm/gemini.py` 의 `generate_structured` 가 아래
# `structured_model` 로 이 집합을 보고 `gemini_*_judgment_model_name`·`gemini_publish_filter_model_name` 설정을
# 고른다. 그래서 call_site 를 새로 만들거나 합치거나 나누면 그 호출이 어느 모델로 가는지도 바뀐다.
# 새 판정·심사 call_site 는 알맞은 종류에 넣어야 스위치를 따라가고, 빠뜨리면 조용히 기본 모델로 돈다.
# 기억 요약(`chat_memory_summary`)은 매 턴 생성 프롬프트에 실려 생성 품질에 바로 닿고, 시드
# 스크립트 호출은 운영 판정이 아니라서 어느 집합에도 넣지 않는다.
# 판정을 종류별로 나누는 건 모델을 바꿨을 때 품질이 종류마다 따로 움직여서다 — 같은 비교에서 스탯·엔딩은
# 현행과 맞았지만 그림 매칭은 어긋나, 셋을 한 스위치로 묶으면 옮길 수 있는 둘까지 묶인다.
STAT_JUDGMENT_CALL_SITES: frozenset[LLMCallSite] = frozenset({"chat_stat_judgment", "preview_stat_judgment"})
ENDING_JUDGMENT_CALL_SITES: frozenset[LLMCallSite] = frozenset({"chat_ending_judgment", "preview_ending_judgment"})
IMAGE_JUDGMENT_CALL_SITES: frozenset[LLMCallSite] = frozenset(
    {"chat_situational_image", "chat_media_book_image", "preview_media_book_image"}
)
# 판정 전체. 어드민 사용량 화면이 판정 비율(판정 호출 ÷ 생성 호출)을 낼 call_site 를 이것으로 가른다.
JUDGMENT_CALL_SITES: frozenset[LLMCallSite] = (
    STAT_JUDGMENT_CALL_SITES | ENDING_JUDGMENT_CALL_SITES | IMAGE_JUDGMENT_CALL_SITES
)
# 발행 심사는 실패하면 발행이 막히는(fail-closed) 경로라 판정과 따로 바꾸고 되돌릴 수 있게 둔다.
PUBLISH_FILTER_CALL_SITES: frozenset[LLMCallSite] = frozenset(
    {"publish_filter_character", "publish_filter_story"}
)


def structured_model(call_site: LLMCallSite, default_model: str) -> str:
    """구조화 호출 하나가 실제로 쓸 모델. 판정 종류·발행 심사 집합이면 그 스위치의 값을, 아니면 `default_model` 을
    돌려준다. Gemini 클라이언트가 호출마다 이 함수로 모델을 고르고, 발행 심사의 통과 기억도 같은 함수로 모델을
    구한다 — 둘이 따로 계산하면 심사 모델이 바뀌었는데 옛 모델의 통과로 심사를 건너뛸 수 있다.

    설정은 호출마다 읽는다 — 클라이언트가 프로세스당 하나이고 설정은 실행 중에 바뀌지 않아 운영에서는
    기동 때 읽는 것과 같다. 모델명을 `or` 로 고르는 건 env 에 키만 남아 빈 문자열이 들어와도 기본
    모델로 돌게 하려는 것이다(빈 모델명은 어떤 모델도 가리키지 않는다)."""
    if call_site in STAT_JUDGMENT_CALL_SITES:
        return settings.gemini_stat_judgment_model_name or default_model
    if call_site in ENDING_JUDGMENT_CALL_SITES:
        return settings.gemini_ending_judgment_model_name or default_model
    if call_site in IMAGE_JUDGMENT_CALL_SITES:
        return settings.gemini_image_judgment_model_name or default_model
    if call_site in PUBLISH_FILTER_CALL_SITES:
        return settings.gemini_publish_filter_model_name or default_model
    return default_model


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
