import type { components } from "@ai-character-chat/api-types";

export type CloverPayMethodItem = components["schemas"]["CloverPayMethodItem"];

/** 결제수단 하나를 폼 값(문자열)으로 접는다. 카드는 `CARD`, 간편결제는 `EASY_PAY:제공자`. */
export function toPayMethodKey(item: CloverPayMethodItem): string {
  return item.easyPayProvider === null ? item.payMethod : `${item.payMethod}:${item.easyPayProvider}`;
}

export function findPayMethod(items: CloverPayMethodItem[], key: string): CloverPayMethodItem | undefined {
  return items.find((item) => toPayMethodKey(item) === key);
}

/** 선택지 라벨. 목록 자체는 서버가 정하고(심사가 끝난 수단만), 여기는 이름만 붙인다 — 모르는 제공자는 서버 값 그대로
 * 보인다(목록에서 빠지지 않게). */
const EASY_PAY_LABELS: Record<string, string> = {
  KAKAOPAY: "카카오페이",
  NAVERPAY: "네이버페이",
  TOSSPAY: "토스페이",
  SSGPAY: "SSG페이",
  LPAY: "L.pay",
  SAMSUNGPAY: "삼성페이",
  APPLEPAY: "애플페이",
  PAYCO: "페이코",
};

export function formatPayMethodLabel(item: CloverPayMethodItem): string {
  if (item.easyPayProvider === null) return "카드";
  return EASY_PAY_LABELS[item.easyPayProvider] ?? item.easyPayProvider;
}
