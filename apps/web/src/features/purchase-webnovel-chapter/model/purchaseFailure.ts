import { isApiError } from "@/shared/api/client";
import { getRateLimitDetail } from "@/shared/api/rateLimit";

/** 소장 요청이 실패했을 때 확인 화면이 할 일.
 *
 * - `insufficient`: 잔액 부족(429 `CLOVER_REQUIRED`). 화면의 잔액이 낡았던 것이다 — 잔액 부족 모양으로 바꿔 보인다.
 * - `priceChanged`: 확인 화면의 가격이 지금 가격과 다르다(409). 지금 가격으로 다시 묻는다.
 * - `notForSale`: 무료 화이거나 게시자 본인이라 살 것이 없다(409) — 이미 읽을 수 있는 화다.
 * - `missing`: 지금 읽을 수 있는 공개 화가 아니다(404 — 그사이 공개가 끝났거나 노벨이 꺼졌다).
 * - `failed`: 그 밖(네트워크·5xx·재동의 등) — 다시 시도할 수 있다. */
export type PurchaseFailure =
  | { kind: "insufficient" }
  | { kind: "priceChanged"; currentPrice: number }
  | { kind: "notForSale" }
  | { kind: "missing" }
  | { kind: "failed" };

export function toPurchaseFailure(error: unknown): PurchaseFailure {
  if (getRateLimitDetail(error)?.code === "CLOVER_REQUIRED") return { kind: "insufficient" };
  if (!isApiError(error)) return { kind: "failed" };
  if (error.status === 404) return { kind: "missing" };
  const detail = typeof error.detail === "object" && error.detail !== null ? error.detail : undefined;
  if (error.status === 409 && detail?.code === "NOVEL_READ_PRICE_CHANGED" && typeof detail.currentPrice === "number") {
    return { kind: "priceChanged", currentPrice: detail.currentPrice };
  }
  if (error.status === 409 && detail?.code === "NOVEL_CHAPTER_NOT_FOR_SALE") return { kind: "notForSale" };
  return { kind: "failed" };
}
