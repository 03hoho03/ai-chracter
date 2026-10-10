"""어드민 사용량 화면의 추정 원가를 내는 모델별 단가표(USD / 1M 토큰).

손으로 옮긴 상수라 **낡는다** — Google·Anthropic 이 가격을 바꾸거나 새 모델을 쓰기 시작해도 저절로 따라오지
않는다. 그래서 확인일(`PRICES_AS_OF`)을 화면에 같이 띄우고, 표에 없는 모델은 원가를 0 이 아니라
"단가 없음"으로 비운다. 가격이 바뀌었으면 값과 확인일을 함께 고친다.

Gemini 의 출처는 Gemini Developer API 가격 페이지(ai.google.dev/gemini-api/docs/pricing)의 Paid tier
Standard 값이다. 입력은 텍스트·이미지 단가, 출력은 사고 토큰을 포함한 단가다(사고 토큰은 출력
단가로 과금된다). 입력 길이(200k)로 단가가 갈리는 Pro 계열은 넣지 않았다 — 일 단위 합산으로는 호출별 길이를 알 수 없다.

Claude 의 출처는 Anthropic 가격 문서(platform.claude.com/docs/en/about-claude/pricing)의 정가이고, 키는 실제로 호출하는
Bedrock 모델 id 다. Bedrock 의 global 교차 리전 프로필이 이 정가와 같다고 보고 넣었다 — Bedrock 가격 페이지에서 서울 값을 직접
읽은 것은 아니라서, 청구서가 나오면 대조한다. 지역 프로필은 global 보다 10% 비싸다고 Anthropic 문서에 적혀 있어, 호출 프로필을
바꾸면 이 값도 바꾼다. 캐시 쓰기는 5분 수명 캐시의 단가다. Gemini 는 캐시 쓰기를 따로 과금하지 않아 그 단가가 0 이다.
Anthropic API 로 직접 부르는 id(`claude-` 로 시작)는 같은 문서의 정가 그대로다. 그중 Opus 5.5·Sonnet 5.5 는 캐시 읽기가 입력의
0.05 배라(다른 모델은 0.1 배) 관례로 짐작하지 않고 표 값을 옮겼다. 이 두 줄은 2026-10-10 에 확인했다 — `PRICES_AS_OF` 는
표 전체를 다시 확인한 날이라 다른 줄과 함께 다시 볼 때 고친다. 요청에 처리 지역을 싣지 않으므로 워크스페이스 기본값이 미국
지정이면 실제 단가는 이 값의 1.1 배다. 판정 전용 Haiku 4.5 의 두 줄(Bedrock global 프로필·직접 API)은 2026-10-10 에 같은 문서의 표
값(입력·5분 캐시 쓰기·캐시 읽기·출력)을 옮겼다.

3.8 Flash 는 2026-12-31 까지 할인가가 붙어 있는데, 할인가를 넣으면 날짜가 지나 조용히 틀린 값이 된다. 그래서 2027-01-01
부터의 정가로 넣었다 — 연말까지는 원가를 실제의 두 배로 높게 보인다(낮게 보이는 쪽보다 안전하다). 할인가가 붙은 다른
3.6·3.7 Flash 는 쓰지 않아 넣지 않았다.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ModelPrice:
    input_usd_per_million: float
    cached_input_usd_per_million: float
    output_usd_per_million: float
    cache_write_usd_per_million: float = 0.0


PRICES_AS_OF = date(2026, 10, 6)

MODEL_PRICES: dict[str, ModelPrice] = {
    "gemini-3.5-flash-lite": ModelPrice(0.30, 0.03, 2.50),
    "gemini-3.1-flash-lite": ModelPrice(0.25, 0.025, 1.50),
    "gemini-3.5-flash": ModelPrice(1.50, 0.15, 9.00),
    "gemini-3.8-flash": ModelPrice(1.50, 0.15, 7.50),
    "gemini-3-flash-preview": ModelPrice(0.50, 0.05, 3.00),
    "gemini-2.5-flash": ModelPrice(0.30, 0.03, 2.50),
    "gemini-2.5-flash-lite": ModelPrice(0.10, 0.01, 0.40),
    "global.anthropic.claude-sonnet-4-6": ModelPrice(3.00, 0.30, 15.00, cache_write_usd_per_million=3.75),
    "global.anthropic.claude-opus-4-6-v1": ModelPrice(5.00, 0.50, 25.00, cache_write_usd_per_million=6.25),
    "claude-opus-5-5": ModelPrice(4.00, 0.20, 20.00, cache_write_usd_per_million=5.00),
    "claude-sonnet-5-5": ModelPrice(2.00, 0.10, 10.00, cache_write_usd_per_million=2.50),
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": ModelPrice(1.00, 0.10, 5.00, cache_write_usd_per_million=1.25),
    "claude-haiku-4-5": ModelPrice(1.00, 0.10, 5.00, cache_write_usd_per_million=1.25),
}


def estimate_cost_usd(
    model: str,
    *,
    input_tokens: int,
    cached_tokens: int,
    output_tokens: int,
    thoughts_tokens: int,
    cache_write_tokens: int = 0,
) -> float | None:
    """단가표에 없는 모델이면 None. `input_tokens` 는 캐시 읽기·쓰기를 포함한 입력 전체다 — Gemini SDK 는 입력 토큰 수를
    캐시 적중을 포함해 보고하고, Claude 는 빼고 보고하지만 사용량 기록이 셋을 더해 둔다(`llm/usage_store.py`). 그래서
    정가로 치는 몫은 그 둘을 뺀 차이다."""
    price = MODEL_PRICES.get(model)
    if price is None:
        return None
    uncached = max(input_tokens - cached_tokens - cache_write_tokens, 0)
    return (
        uncached * price.input_usd_per_million
        + cached_tokens * price.cached_input_usd_per_million
        + cache_write_tokens * price.cache_write_usd_per_million
        + (output_tokens + thoughts_tokens) * price.output_usd_per_million
    ) / 1_000_000
