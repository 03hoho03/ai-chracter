import abc
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from api.core.config import settings
from api.llm.call_policy import CALL_POLICIES, BackendId

# `as LLMCallSite` 는 mypy strict 의 명시적 재export 요구 때문이다 — 이 이름을 `api.llm.client` 에서 가져오는 모듈이
# 많아, 정의를 호출 정책 표 옆으로 옮겨도 기존 import 경로를 그대로 쓰게 둔다.
from api.llm.call_policy import LLMCallSite as LLMCallSite
from api.llm.chat_models import DEFAULT_CHAT_MODEL, ChatModelId

T = TypeVar("T", bound=BaseModel)

# 아래 집합들은 로그 라벨이면서 **모델 선택도 겸한다** — `llm/gemini.py` 의 `generate_structured` 가 아래
# `structured_model` 로 이 집합을 보고 `gemini_*_judgment_model_name`·`gemini_publish_filter_model_name` 설정을
# 고른다. 그래서 call_site 를 새로 만들거나 합치거나 나누면 그 호출이 어느 모델로 가는지도 바뀐다.
# 집합은 `llm/call_policy.py` 의 호출 정책 표에서 만든다 — 새 판정·심사 call_site 는 그 표의 행에 알맞은 종류를 적어야
# 스위치를 따라가고, 빠뜨리면 조용히 기본 모델로 돈다.
STAT_JUDGMENT_CALL_SITES: frozenset[LLMCallSite] = frozenset(
    cs for cs, p in CALL_POLICIES.items() if p.judgment_kind == "stat"
)
ENDING_JUDGMENT_CALL_SITES: frozenset[LLMCallSite] = frozenset(
    cs for cs, p in CALL_POLICIES.items() if p.judgment_kind == "ending"
)
IMAGE_JUDGMENT_CALL_SITES: frozenset[LLMCallSite] = frozenset(
    cs for cs, p in CALL_POLICIES.items() if p.judgment_kind == "image"
)
# 판정 전체. 어드민 사용량 화면이 판정 비율(판정 호출 ÷ 생성 호출)을 낼 call_site 를 이것으로 가른다.
JUDGMENT_CALL_SITES: frozenset[LLMCallSite] = (
    STAT_JUDGMENT_CALL_SITES | ENDING_JUDGMENT_CALL_SITES | IMAGE_JUDGMENT_CALL_SITES
)
PUBLISH_FILTER_CALL_SITES: frozenset[LLMCallSite] = frozenset(cs for cs, p in CALL_POLICIES.items() if p.publish_filter)
# 소설화 호출 전체 — 공급자 구현들이 잘림·빈 본문을 구분된 실패로 올리는 호출.
NOVELIZE_CALL_SITES: frozenset[LLMCallSite] = frozenset(cs for cs, p in CALL_POLICIES.items() if p.novelize is not None)
# 그중 소설화 모델·출력 상한·사고 설정(`gemini_novelize_*`)을 쓰는 호출 — 본문을 쓰는 장 생성과 문단 수정이다.
NOVELIZE_MODEL_CALL_SITES: frozenset[LLMCallSite] = frozenset(
    cs for cs, p in CALL_POLICIES.items() if p.novelize == "prose"
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
    if call_site in NOVELIZE_MODEL_CALL_SITES:
        return settings.gemini_novelize_model_name or default_model
    return default_model


def request_timeout_ms(call_site: LLMCallSite) -> int:
    """호출 하나가 요청에 실을 타임아웃(ms). 어느 값을 쓸지는 호출 정책 표의 `gemini_timeout` 이 정하고, 설정 이름이면
    `core/config.py` 의 그 `gemini_*_timeout_ms` 값을 호출마다 읽는다. 모든 call_site 가 값을 받는다 — 요청 단위 값 없이
    나간 호출이 한 번이라도 있으면 SDK 가 클라이언트 헤더에 전역값의 서버 기한 헤더를 써 넣어, 뒤따르는 호출이 자기
    값을 헤더에 싣지 못한다."""
    timeout = CALL_POLICIES[call_site].gemini_timeout
    if isinstance(timeout, int):
        return timeout
    value: int = getattr(settings, timeout)
    return value


class SegmentedPrompt(str):
    """블록 경계를 함께 싣는 프롬프트 문자열. 값은 `segments` 를 이은 것 그대로라, 문자열로만 다루는 쪽(프롬프트 덤프, 응답
    모델, 테스트 가짜)에는 보통의 `str` 과 똑같다. 경계를 읽는 것은 Claude 구현뿐이다(프롬프트 캐시의 블록).
    예외는 타입을 정확히 `str` 로 따지는 외부 라이브러리다 — Gemini SDK 는 하위 클래스를 빈 내용으로 바꿔 보내므로, Gemini
    구현이 SDK 에 넘기기 직전에 보통의 `str` 로 바꾼다.

    값을 조각에서만 만들어 "이으면 원문과 바이트까지 같다"가 늘 참이다. `+`·`strip` 같은 문자열 연산의 결과는 보통의
    `str` 이라 경계가 사라진다 — 틀린 글이 나가지는 않고 캐시만 못 맞는다."""

    segments: tuple[str, ...]

    def __new__(cls, segments: tuple[str, ...]) -> "SegmentedPrompt":
        prompt = super().__new__(cls, "".join(segments))
        prompt.segments = segments
        return prompt


@dataclass(frozen=True)
class CallUsage:
    """턴 기록(`chat_turns.llm_calls`)에 남는 호출 한 건의 사용량. 토큰 칸은 SDK 가 보고한 값 그대로이고, 보고하지 않은
    칸은 `None` 이다(이미지가 실린 호출은 입력 토큰이 오지 않는다). 입력 토큰은 캐시를 포함한 전체다 — Claude 사용량도
    공급자 모듈이 같은 뜻으로 옮겨 온다."""

    call_site: str
    model: str
    prompt_tokens: int | None
    cached_tokens: int | None
    cache_write_tokens: int | None
    output_tokens: int | None
    thoughts_tokens: int | None

    def as_record(self) -> dict[str, Any]:
        return {
            "callSite": self.call_site,
            "model": self.model,
            "promptTokens": self.prompt_tokens,
            "cachedTokens": self.cached_tokens,
            "cacheWriteTokens": self.cache_write_tokens,
            "outputTokens": self.output_tokens,
            "thoughtsTokens": self.thoughts_tokens,
        }


def _token_count(usage_metadata: object | None, attr: str) -> int | None:
    value = getattr(usage_metadata, attr, None)
    return value if isinstance(value, int) else None


def collect_usage(usage: "LLMCallContext", model: str, usage_metadata: object | None) -> None:
    """호출 한 건을 그 호출의 `usage_sink` 에 더한다(없으면 아무것도 하지 않는다). 공급자 구현이 `record_usage` 를 부르는
    바로 그 자리에서 함께 부른다 — 그래서 더하는 조건(스트림은 정상 종료 때만, 구조화는 파싱 검사 앞)이 사용량 집계와
    같다. 생성 스트림 안에서 불리므로 메타데이터가 이상해도 예외를 내지 않게 정수가 아닌 값은 `None` 으로 읽는다."""
    if usage.usage_sink is None:
        return
    usage.usage_sink.append(
        CallUsage(
            call_site=usage.call_site,
            model=model,
            prompt_tokens=_token_count(usage_metadata, "prompt_token_count"),
            cached_tokens=_token_count(usage_metadata, "cached_content_token_count"),
            cache_write_tokens=_token_count(usage_metadata, "cache_write_token_count"),
            output_tokens=_token_count(usage_metadata, "candidates_token_count"),
            thoughts_tokens=_token_count(usage_metadata, "thoughts_token_count"),
        )
    )


@dataclass(frozen=True)
class LLMCallContext:
    """호출 한 건의 사용량을 누구·어디에 귀속할지. 필수 키워드 인자라 새 호출부가
    빠뜨리면 mypy가 잡는다. `room_id`는 DB 방이 없는 호출(미리보기·발행 심사·스크립트)에서 None.

    `model` 은 사용자가 고른 글쓰기 모델이다. 앞의 셋과 달리 기본값(Gemini)이 있다 — 모델을 고를 수 있는 호출은 채팅 턴
    생성, 지난 턴 다시 생성(측정용 리플레이), 소설 장 생성뿐이고, 나머지 호출부가 빠뜨려도 Gemini 로 가는 것이 맞는 동작이라서다.
    빠뜨리는 실수가 비싼 모델로 새는 방향이 아니다. 이 값을 보고 공급자를 고르는 것은 `llm/routing.py` 이고, 거기서도 그 호출들만
    따른다."""

    call_site: LLMCallSite
    user_id: uuid.UUID | None
    room_id: uuid.UUID | None
    model: ChatModelId = DEFAULT_CHAT_MODEL
    # 이 호출의 사용량을 모을 목록. 채팅 턴 골격만 넘기고(방 턴은 모은 것을 턴 기록에 싣는다) 나머지 호출부는 두지 않는다 —
    # 기본값이 None 이라 기존 호출부와 테스트 가짜는 그대로다. 비교·해시에서 빼는 것은 이 칸이 호출의 귀속(누구·어디)이 아니라
    # 모으는 자리라서이고, 목록은 해시할 수 없어 넣으면 이 frozen 데이터클래스의 해시가 TypeError 가 된다.
    usage_sink: list[CallUsage] | None = field(default=None, compare=False, hash=False)


class LLMClientError(Exception):
    """Raised when an LLM provider call fails or returns an unusable response.

    `provider` 는 실패한 호출의 공급자다. 클래스 기본값이 Gemini 라 Gemini 클라이언트와 기존 호출부는 그대로이고, Claude
    클라이언트들만 자기가 올리는 예외에 자기 이름(`bedrock`·`anthropic`)을 적는다. Bugsink 태그(`dependency_tag`)가 이 값으로
    갈린다."""

    provider: BackendId = "gemini"


class LLMPolicyViolationError(LLMClientError):
    """Raised when the provider's safety filtering blocks a prompt or its output."""


class LLMRateLimitError(LLMClientError):
    """Raised when the provider reports quota exhaustion (HTTP 429).

    `llm/gemini.py`가 네트워크 타임아웃(`httpx.HTTPError`)과
    쿼터 소진(`genai_errors.APIError(code=429)`)을 구분하려고 두는 서브클래스다 — 여전히
    `LLMClientError`라 기존 `except LLMClientError`가 그대로 잡으므로 사용자에게 보이는
    동작(흡수)은 바뀌지 않는다. 호출부는 `isinstance` 검사로 승격 이벤트의 태그만 갈라 붙인다."""


class LLMTruncatedError(LLMClientError):
    """소설화 호출의 출력이 출력 상한(`MAX_TOKENS`)에서 잘렸다. 채팅 호출에서는 올라오지 않는다 — 채팅은 잘린 응답을
    경고 로그만 남기고 그대로 돌려준다. 사용량은 이 예외를 올리기 전에 이미 기록됐다."""


class LLMEmptyResponseError(LLMClientError):
    """소설화 호출이 끝났는데 본문이 비었다(공백뿐인 것 포함). 대개 종료 사유가 정상(STOP)이라 그것만 보면 성공으로
    보인다. 사용량은 이 예외를 올리기 전에 이미 기록됐다. 비지는 않았지만 너무 짧은 본문을 실패로 볼 기준은 호출부가
    정한다.

    사고를 끌 수 없는 Anthropic API 직접 구현에서는 사고가 출력 상한을 다 써 본문 없이 끝난 경우(종료 사유 `max_tokens`)도
    이 예외다 — 소설 장에서는 출력 상한에 닿았어도 `LLMTruncatedError` 가 아니라 이것이고, 채팅 호출에서는 이 경우에만
    올라온다(빈 턴을 저장·과금하지 않고 환불 경로를 태운다)."""


def dependency_tag(exc: LLMClientError) -> str:
    """흡수한 LLM 실패를 Bugsink 로 승격할 때의 `dependency` 태그. 공급자마다 이름이 따로다(`gemini`·`gemini_rate_limit`,
    `bedrock`·`bedrock_rate_limit`, `anthropic`·`anthropic_rate_limit`) — 한 이름으로 합치면 기존 Gemini 이벤트 묶음과 로그
    검색이 끊긴다. 쿼터 소진(429)을 다른 실패와 갈라 붙여야 승격된 이벤트로 행동할 수 있다."""
    if isinstance(exc, LLMRateLimitError):
        return f"{exc.provider}_rate_limit"
    return exc.provider


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

    async def generate_structured_with_instruction(
        self,
        prompt: str,
        response_schema: type[T],
        *,
        system_instruction: str,
        usage: LLMCallContext,
    ) -> T:
        """`generate_structured` 와 같되 역할 규칙을 본문과 다른 통로(`system_instruction`)로 보낸다. 소설화의 문단
        수정·경계 제안이 쓴다 — 본문이 사용자·작가가 쓴 글이라 규칙과 섞이면 그 글이 지시처럼 읽힐 수 있다.

        추상 메서드가 아니다. `generate_structured` 에 인자를 더하면 그 메서드를 구현한 테스트 페이크 전부의
        시그니처를 함께 바꿔야 해서, 이 호출을 쓰는 클라이언트(Gemini)와 소설화 테스트 페이크만 따로 구현한다."""
        raise NotImplementedError
