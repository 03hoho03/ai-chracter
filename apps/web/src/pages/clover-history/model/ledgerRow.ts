import { CLOVER_KIND_LABELS, formatCloverLedgerAmount, type CloverLedgerItem } from "@/entities/clover";

/** 내역 한 행을 어떻게 그릴지.
 *
 * 클로버 단위를 바꾼 기록(범주 `conversion`)은 사용·획득·소멸 어느 탭에나 함께 실려 온다 — 서버가 그렇게 싣는다. 그
 * 행은 거래가 아니라 "여기서 단위가 바뀌었다"는 경계라 금액 행으로 그리지 않고 경계 줄로 그린다. 경계 줄은 날짜와 그때의
 * 잔액만 말한다(전환 뒤 잔액은 새 단위다).
 *
 * 나머지 행 중 전환 전의 단위로 적힌 것(`legacyUnit`)에는 '이전 단위' 표시를 붙인다 — 그 행의 숫자는 지금 잔액과 같은
 * 단위로 더하고 뺄 수 없다. 표시 여부는 서버가 전환 기록과 행 시각으로 판정해 싣는다(화면이 다시 판정하지 않는다). */
export type LedgerRowView =
  | { kind: "boundary"; label: string; balanceAfter: string }
  | { kind: "entry"; label: string; amount: string; isLegacyUnit: boolean };

export function toLedgerRowView(item: CloverLedgerItem): LedgerRowView {
  const label = CLOVER_KIND_LABELS[item.kind] ?? item.kind;
  if (item.category === "conversion") {
    return { kind: "boundary", label, balanceAfter: item.balanceAfter.toLocaleString() };
  }
  return { kind: "entry", label, amount: formatCloverLedgerAmount(item.amount), isLegacyUnit: item.legacyUnit };
}
