"""Claude Messages API 를 쓰는 구현(`llm/bedrock.py`·`llm/anthropic_api.py`)이 함께 쓰는 요청·응답 조각.

같은 Messages API 라 요청 블록·스트림 이벤트·사용량의 모양이 같다. 구현마다 다른 것 — SDK 와 자격, 요청에 더 싣는 값
(Bedrock 은 사고 끔, 직접 API 는 사고 깊이), 스로틀 판별, 잡을 전송 예외, 로그 줄과 사용량 기록 — 은 각 구현에 남긴다.

스트림 읽기는 이벤트 하나를 먹는 집계기(`ClaudeStreamTally.feed`)이고 제너레이터가 아니다. 읽기 루프를 여기 두는 안쪽
제너레이터로 만들면 소비자가 중간에 끊을 때(aclose) 바깥 제너레이터만 닫히고 SDK 스트림을 쥔 안쪽은 가비지 수거까지
남는다 — 그래서 `async for`·`except`·사용량 기록은 구현이 자기 제너레이터 한 겹 안에서 한다. 같은 이유로 이 모듈은 사용량
기록(`record_usage`)을 부르지 않는다. 리플레이가 구현 모듈마다의 그 이름을 바꿔 끼워 보낸 호출을 잡기 때문이다. 로그도
남기지 않고(빌더와 어긋난 캐시 경계 경고는 구현의 로거를 받아 남긴다) — 로그 줄의 로거 이름이 구현마다 따로라야 기존 검색이
끊기지 않는다.
"""

import logging
from dataclasses import dataclass
from typing import Any, TypeVar

import anthropic
import httpx
import httpx2
from anthropic.types import TextBlockParam

from api.llm.call_policy import CALL_POLICIES, BackendId
from api.llm.client import (
    NOVELIZE_CALL_SITES,
    LLMCallSite,
    LLMClientError,
    LLMEmptyResponseError,
    LLMPolicyViolationError,
    LLMTruncatedError,
    SegmentedPrompt,
)

E = TypeVar("E", bound=LLMClientError)

# 두 구현이 함께 잡는 전송 예외. SDK 는 요청 단계의 실패를 자기 예외(`AnthropicError` 계열)로 바꾸지만, 스트림을 읽는 도중의
# 네트워크 실패는 자기가 쓰는 `httpx2` 예외 그대로 올린다. `httpx`(이 저장소의 다른 SDK 가 쓰는 쪽)와 `TimeoutError` 는
# 전송 계층이 바뀌어도 SSE 본문을 뚫지 않게 함께 잡는다.
COMMON_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    anthropic.AnthropicError,
    httpx2.HTTPError,
    httpx.HTTPError,
    TimeoutError,
)


def claude_error(cls: type[E], message: str, provider: BackendId) -> E:
    """구현이 올리는 예외에 공급자를 적는다 — Bugsink 태그(`dependency_tag`)가 이 값으로 갈린다."""
    exc = cls(message)
    exc.provider = provider
    return exc


def user_content(prompt: str, call_site: LLMCallSite, logger: logging.Logger) -> str | list[TextBlockParam]:
    """대본을 user 메시지 내용으로 만든다. 채팅 턴은 빌더가 나눈 블록 셋으로 보내고 둘째 블록(대화 기록 끝)에만 캐시
    체크포인트를 단다 — 다음 턴은 이 턴의 첫째·둘째 블록을 이은 것을 첫째 블록으로 보내므로, 자기 첫째 블록 경계에서 이
    체크포인트가 쓴 캐시를 찾는다. 셋째 블록(키워드북·현재 상황·이번 입력)은 턴마다 바뀌어 표시하지 않는다. system 은
    메시지보다 앞이라 체크포인트까지의 앞부분에 저절로 들어간다. 체크포인트까지가 모델별 최소 캐시 길이보다 짧으면 API 는
    오류 없이 캐시만 하지 않으므로 길이를 따로 재지 않는다.

    소설 장은 장마다 내용이 거의 다 바뀌어 캐시 쓰기 할증만 내므로 걸지 않는다. 경계가 없는 채팅 턴(보통 문자열)은 하나로
    보낸다 — 빌더는 대화 기록이 빈 턴에 일부러 보통 문자열을 내고, 기록이 있는데 나누지 못한 턴은 이유를 아는 빌더가 경고로
    남긴다. 여기서는 경계가 있는데 셋이 아닌 경우(빌더와 이 구현이 어긋난 것)만 구현의 로거로 경고를 남긴다.

    지난 턴을 다시 생성하는 측정 호출(`replay_generate`)도 같은 블록·체크포인트로 보낸다 — 실제 생성과 같은 요청 모양이라야
    원가·지연 측정이 맞고, 같은 턴을 여러 번 돌릴 때 앞부분을 캐시로 싸게 읽는다."""
    if CALL_POLICIES[call_site].claude_cache_checkpoint and isinstance(prompt, SegmentedPrompt):
        if len(prompt.segments) == 3:
            first, history_end, rest = prompt.segments
            return [
                {"type": "text", "text": first},
                {"type": "text", "text": history_end, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": rest},
            ]
        try:
            # 로그 실패가 턴을 막지 않게 한다(사용량 로그와 같은 규칙).
            logger.warning(
                "채팅 턴 프롬프트의 캐시 경계가 셋이 아니라 블록 하나로 보낸다(조각 %d개)", len(prompt.segments)
            )
        except Exception:
            pass
    return str(prompt)


@dataclass(frozen=True)
class ClaudeUsage:
    """Claude 의 사용량을 Gemini 사용량 메타데이터의 속성 이름으로 옮긴 것 — 사용량 기록(`record_usage`)과 어드민 원가가
    공급자를 가리지 않고 같은 열을 읽게 한다. Claude 의 입력 토큰은 캐시 읽기·쓰기를 뺀 값이라, Gemini 처럼 캐시를 포함한
    입력 전체가 되게 셋을 더한다. Claude 의 출력 토큰은 사고를 포함한 과금 총량이라, 응답이 사고 내역을 실어 오면 그 몫을
    `thoughts` 로 떼어 낸다(내역이 없으면 0 — 사고를 끄는 Bedrock 이 그렇다). 원가는 출력과 사고를 같은 단가로 더하므로
    어느 쪽이든 같다."""

    prompt_token_count: int
    cached_content_token_count: int
    cache_write_token_count: int
    candidates_token_count: int
    thoughts_token_count: int
    total_token_count: int


def to_usage(
    input_tokens: int, cache_read: int, cache_write: int, output_tokens: int, thinking_tokens: int | None = None
) -> ClaudeUsage:
    prompt = input_tokens + cache_read + cache_write
    thoughts = thinking_tokens or 0
    return ClaudeUsage(
        prompt_token_count=prompt,
        cached_content_token_count=cache_read,
        cache_write_token_count=cache_write,
        candidates_token_count=output_tokens - thoughts,
        thoughts_token_count=thoughts,
        total_token_count=prompt + output_tokens,
    )


class ClaudeStreamTally:
    """스트림 이벤트를 하나씩 먹어 사용량·종료 사유를 모으고, 내보낼 본문 조각만 돌려준다. `text_delta` 만 본문이다 —
    사고 블록(`thinking_delta`·`signature_delta`)과 그 밖의 이벤트는 내보내지 않는다.

    `label` 은 예외 문구 앞에 붙는 공급자 이름이다(로그·Bugsink 의 문구가 구현마다 지금 그대로 남게)."""

    def __init__(self, provider: BackendId, label: str) -> None:
        self.provider = provider
        self.label = label
        self.truncated = False
        self.has_text = False
        self._input_tokens: int | None = None
        self._cache_read = 0
        self._cache_write = 0
        self._output_tokens = 0
        self._thinking_tokens: int | None = None

    def feed(self, event: Any) -> str | None:
        """정책 거절(`refusal`)이면 `LLMPolicyViolationError` 를 올린다. 출력 상한(`max_tokens`)에서 끝나면 `truncated` 를
        세운다 — 무엇을 실패로 볼지는 정상 종료 뒤 `raise_if_unusable`(와 구현)이 정한다."""
        if event.type == "message_start":
            start_usage = event.message.usage
            self._input_tokens = start_usage.input_tokens
            self._cache_read = start_usage.cache_read_input_tokens or 0
            self._cache_write = start_usage.cache_creation_input_tokens or 0
            self._output_tokens = start_usage.output_tokens
        elif event.type == "content_block_delta":
            if event.delta.type == "text_delta" and event.delta.text:
                self.has_text = self.has_text or bool(event.delta.text.strip())
                text: str = event.delta.text
                return text
        elif event.type == "message_delta":
            # 사용량은 누적값으로 온다. 입력·캐시 값이 실려 오면 시작 때의 값보다 이것이 최종이다.
            delta_usage = event.usage
            self._output_tokens = delta_usage.output_tokens
            if delta_usage.input_tokens is not None:
                self._input_tokens = delta_usage.input_tokens
            if delta_usage.cache_read_input_tokens is not None:
                self._cache_read = delta_usage.cache_read_input_tokens
            if delta_usage.cache_creation_input_tokens is not None:
                self._cache_write = delta_usage.cache_creation_input_tokens
            # 사고 내역은 사고하는 모델만 싣는다. 실려 오지 않는 응답(사고를 끈 Bedrock)도 있어 없으면 그대로 둔다.
            details = getattr(delta_usage, "output_tokens_details", None)
            if details is not None:
                self._thinking_tokens = details.thinking_tokens
            if event.delta.stop_reason == "refusal":
                raise claude_error(LLMPolicyViolationError, f"{self.label} Claude refused to continue", self.provider)
            if event.delta.stop_reason == "max_tokens":
                self.truncated = True
        return None

    def usage(self) -> ClaudeUsage | None:
        """`message_start` 를 못 받았으면 None — 사용량 기록이 `missing` 으로 센다."""
        if self._input_tokens is None:
            return None
        return to_usage(
            self._input_tokens, self._cache_read, self._cache_write, self._output_tokens, self._thinking_tokens
        )


def raise_if_unusable(tally: ClaudeStreamTally, call_site: LLMCallSite, max_tokens: int) -> None:
    """정상 종료한 스트림의 결과를 소설 본문으로 쓸 수 없으면 구분된 실패로 올린다. 사용량을 기록한 **뒤** 부른다. 채팅은
    잘린 응답·빈 응답을 경고만 남기고 그대로 돌려준다."""
    if call_site in NOVELIZE_CALL_SITES:
        if tally.truncated:
            raise claude_error(LLMTruncatedError, f"{tally.label} output hit max_tokens({max_tokens})", tally.provider)
        if not tally.has_text:
            raise claude_error(LLMEmptyResponseError, f"{tally.label} returned an empty body", tally.provider)
