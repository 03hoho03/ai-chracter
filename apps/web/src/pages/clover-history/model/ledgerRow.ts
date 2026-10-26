import { CLOVER_KIND_LABELS, formatCloverLedgerAmount, type CloverLedgerItem } from "@/entities/clover";

/** 내역 한 행을 어떻게 그릴지.
 *
 * 클로버 단위를 바꾼 기록(범주 `conversion`)은 사용·획득·소멸 어느 탭에나 함께 실려 온다 — 서버가 그렇게 싣는다. 그
 * 행은 거래가 아니라 "여기서 단위가 바뀌었다"는 경계라 금액 행으로 그리지 않고 경계 줄로 그린다. 경계 줄은 원장 종류
 * 이름("1원 단위 전환")이 아니라 무슨 일이 있었는지를 사용자 말로 하고, 그때의 잔액(바뀐 단위로 센 값)을 함께 말한다.
 *
 * 나머지 행 중 전환 전의 단위로 적힌 것(`legacyUnit`)에는 '이전 단위' 표시를 붙인다 — 그 행의 숫자는 지금 잔액과 같은
 * 단위로 더하고 뺄 수 없다. 표시 여부는 서버가 전환 기록과 행 시각으로 판정해 싣는다(화면이 다시 판정하지 않는다). */
export type LedgerRowView =
  | { kind: "boundary"; title: string; balance: string }
  | { kind: "entry"; label: string; amount: string; isLegacyUnit: boolean };

/** 단위 전환 기록 종류별 경계 줄 문장. 모르는 종류는 바뀌었다고만 말한다. */
const UNIT_BOUNDARY_TITLES: Record<string, string> = {
  unit_conversion: "클로버 단위가 1원 단위로 바뀌었어요",
  unit_conversion_revert: "클로버 단위가 이전 단위로 돌아갔어요",
};

export function toLedgerRowView(item: CloverLedgerItem): LedgerRowView {
  if (item.category === "conversion") {
    return {
      kind: "boundary",
      title: UNIT_BOUNDARY_TITLES[item.kind] ?? "클로버 단위가 바뀌었어요",
      balance: `이때 잔액 클로버 ${item.balanceAfter.toLocaleString()}개`,
    };
  }
  const label = CLOVER_KIND_LABELS[item.kind] ?? item.kind;
  return { kind: "entry", label, amount: formatCloverLedgerAmount(item.amount), isLegacyUnit: item.legacyUnit };
}

/** 목록에 거래 행이 있는가. 단위 전환 경계 줄은 거래가 아니라서, 경계 줄만 있는 탭은 거래가 없는 탭이다 — 그때도 빈
 * 안내("아직 사용한 클로버가 없어요" 등)를 함께 보여야 그 탭에 거래가 있는 것처럼 읽히지 않는다. */
export function hasLedgerEntries(items: readonly CloverLedgerItem[]): boolean {
  return items.some((item) => item.category !== "conversion");
}
