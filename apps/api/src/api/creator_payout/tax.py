"""지급액에서 떼는 원천징수 — 사업소득(소득세 3% + 지방소득세 = 그 소득세의 10%).

세율과 끝수 처리는 법이 정하는 값이라 설정이 아니라 상수다. 바뀌는 계기는 법 개정이고, 그때는 이 파일과 테스트와 정산
정책 문구를 함께 고친다. 금액은 정수 원으로만 계산한다.

- 소득세: 지급액 × 3%(소득세법 제129조 제1항 제3호), 10원 미만 절사(국고금 관리법 제47조 제1항).
- 지방소득세: **절사한 뒤의** 소득세 × 10%(지방세법 제103조의13 제1항 "원천징수하는 소득세의 100분의 10"), 10원 미만 절사
  (지방회계법 제55조). 두 세목을 합친 3.3% 로 한 번 끊으면 지급액의 약 절반에서 세액이 10원 많아진다.
- 소득세가 1천 원 미만이어도 뗀다. 소득세법 제86조 제1호의 소액부징수는 계속적·반복적으로 공급하는 인적 용역의 사업소득
  (시행령 제149조의3)을 빼고, 크리에이터 정산을 그 소득으로 본다.
"""

from dataclasses import dataclass

# 원천징수대상 사업소득의 소득세율(만분율).
INCOME_TAX_RATE_BPS = 300


@dataclass(frozen=True)
class Withholding:
    income_tax_rate_bps: int
    income_tax_krw: int
    local_tax_krw: int
    net_amount_krw: int


def _floor10(krw: int) -> int:
    return krw // 10 * 10


def withholding(amount_krw: int) -> Withholding:
    """지급액(양의 정수 원)의 원천징수 세액과 실지급액."""
    income_tax = _floor10(amount_krw * INCOME_TAX_RATE_BPS // 10_000)
    local_tax = _floor10(income_tax // 10)
    return Withholding(
        income_tax_rate_bps=INCOME_TAX_RATE_BPS,
        income_tax_krw=income_tax,
        local_tax_krw=local_tax,
        net_amount_krw=amount_krw - income_tax - local_tax,
    )
