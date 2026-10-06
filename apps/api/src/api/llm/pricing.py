"""어드민 사용량 화면의 추정 원가를 내는 모델별 단가표(USD / 1M 토큰).

손으로 옮긴 상수라 **낡는다** — Google 이 가격을 바꾸거나 새 모델을 쓰기 시작해도 저절로 따라오지
않는다. 그래서 확인일(`PRICES_AS_OF`)을 화면에 같이 띄우고, 표에 없는 모델은 원가를 0 이 아니라
"단가 없음"으로 비운다. 가격이 바뀌었으면 값과 확인일을 함께 고친다.

출처는 Gemini Developer API 가격 페이지(ai.google.dev/gemini-api/docs/pricing)의 Paid tier
Standard 값이다. 입력은 텍스트·이미지 단가, 출력은 사고 토큰을 포함한 단가다(사고 토큰은 출력
단가로 과금된다). 입력 길이(200k)로 단가가 갈리는 Pro 계열은 넣지 않았다 — 일 단위 합산으로는 호출별 길이를 알 수 없다.

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


PRICES_AS_OF = date(2026, 10, 6)

MODEL_PRICES: dict[str, ModelPrice] = {
    "gemini-3.5-flash-lite": ModelPrice(0.30, 0.03, 2.50),
    "gemini-3.1-flash-lite": ModelPrice(0.25, 0.025, 1.50),
    "gemini-3.5-flash": ModelPrice(1.50, 0.15, 9.00),
    "gemini-3.8-flash": ModelPrice(1.50, 0.15, 7.50),
    "gemini-3-flash-preview": ModelPrice(0.50, 0.05, 3.00),
    "gemini-2.5-flash": ModelPrice(0.30, 0.03, 2.50),
    "gemini-2.5-flash-lite": ModelPrice(0.10, 0.01, 0.40),
}


def estimate_cost_usd(
    model: str, *, input_tokens: int, cached_tokens: int, output_tokens: int, thoughts_tokens: int
) -> float | None:
    """단가표에 없는 모델이면 None. `input_tokens` 는 캐시 적중분을 포함한 입력 전체다 — SDK 의
    입력 토큰 수가 캐시 적중을 포함해 보고되므로 비캐시분은 그 차이로 낸다."""
    price = MODEL_PRICES.get(model)
    if price is None:
        return None
    uncached = max(input_tokens - cached_tokens, 0)
    return (
        uncached * price.input_usd_per_million
        + cached_tokens * price.cached_input_usd_per_million
        + (output_tokens + thoughts_tokens) * price.output_usd_per_million
    ) / 1_000_000
