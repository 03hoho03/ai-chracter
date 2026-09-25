/** 내역 행의 금액은 부호가 드러나야 한다(+/−). 색으로
 * 구분하지 않는다(평소 무채색, 유채색은 강조 지점에만. `+`/`-` 자체가 유일한 방향 신호다). */
export function formatCloverLedgerAmount(amount: number): string {
  if (amount === 0) return "0";
  const sign = amount > 0 ? "+" : "-";
  return `${sign}${Math.abs(amount).toLocaleString()}`;
}
