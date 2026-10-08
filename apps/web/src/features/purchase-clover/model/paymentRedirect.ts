/** 결제창이 페이지를 떠났다가(모바일) `/clover` 로 돌아올 때 포트원이 붙이는 쿼리 중 이 화면이 읽는 것. 라우트의
 * 서치 스키마가 모양을 고르고, 여기서는 무엇을 할지만 정한다. */
export type PaymentRedirectSearch = {
  paymentId?: string;
  code?: string;
};

/** - `none` — 결제에서 돌아온 것이 아니다.
 * - `complete` — 창이 성공으로 닫혔다. 서버에 확정을 요청한다.
 * - `notCompleted` — 창이 실패 코드로 닫혔다(이용자 취소 포함). 확정을 요청하지 않는다 — `paymentId` 가 함께 와도
 *   그렇다. 포트원은 실패에도 `paymentId` 를 붙인다. */
export type PaymentRedirect = { kind: "none" } | { kind: "complete"; paymentId: string } | { kind: "notCompleted" };

export function resolvePaymentRedirect(search: PaymentRedirectSearch): PaymentRedirect {
  if (search.code !== undefined) return { kind: "notCompleted" };
  if (search.paymentId) return { kind: "complete", paymentId: search.paymentId };
  return { kind: "none" };
}
