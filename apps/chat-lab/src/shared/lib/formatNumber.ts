/** 원가는 소수 넷째 자리로 자리를 고정한다 — 세로로 줄 선 칸에서 `$0.0912` 와 `$2.4187` 의 소수점이 맞는다. */
const USD_FORMAT = new Intl.NumberFormat("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 });

const COUNT_FORMAT = new Intl.NumberFormat("en-US");

export function formatUsd(usd: number): string {
  return `$${USD_FORMAT.format(usd)}`;
}

/** 토큰·개수는 천 단위 쉼표(`18,412`). */
export function formatCount(count: number): string {
  return COUNT_FORMAT.format(count);
}

/** 지연은 ms 정수에 천 단위 쉼표(`2,140ms`). */
export function formatMs(ms: number): string {
  return `${COUNT_FORMAT.format(Math.round(ms))}ms`;
}
