/** 서버가 이미 0.01 달러 단위로 맞춘 금액이라 소수 둘째 자리면 충분하다. 사용량 화면의 달러 표기는 1달러 미만을 넷째 자리까지 보여
 * 규칙이 달라 함께 쓰지 않는다. */
const USD_FORMATTER = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** 서버의 달러 문자열을 표시한다. 계산에 쓰지 않는다 — 금액은 문자열로 주고받고 표시할 때만 숫자로 바꾼다. 음수(추정 초과)는
 * 빼기 기호(U+2212)로 적는다. */
export function formatUsd(value: string): string {
  const amount = Number(value);
  return amount < 0 ? `−${USD_FORMATTER.format(-amount)}` : USD_FORMATTER.format(amount);
}

/** 충전액 대비 추정 잔액의 비율(0~1). 표시 전용이고 임계 아래인지는 서버의 `belowAlert` 를 쓴다. 잔액이 음수이거나 충전액이 0 이하면
 * 비율을 내지 않는다 — 그때는 추정 초과 표지가 금액으로 말한다. */
export function remainingRatio(remainingUsd: string, creditUsd: string): number | undefined {
  const remaining = Number(remainingUsd);
  const credit = Number(creditUsd);
  if (!(credit > 0) || remaining < 0) return undefined;
  return remaining / credit;
}
