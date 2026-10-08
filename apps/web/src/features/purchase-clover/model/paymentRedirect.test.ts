import { describe, expect, it } from "vitest";

import { resolvePaymentRedirect } from "./paymentRedirect";

describe("resolvePaymentRedirect", () => {
  it("paymentId 만 있으면 확정을 요청한다", () => {
    expect(resolvePaymentRedirect({ paymentId: "pay_1" })).toEqual({ kind: "complete", paymentId: "pay_1" });
  });

  // 포트원은 실패에도 paymentId 를 붙인다 — code 를 먼저 보지 않으면 취소한 결제를 확정하러 간다.
  it("code 가 있으면 paymentId 가 함께 와도 확정하지 않는다", () => {
    expect(resolvePaymentRedirect({ paymentId: "pay_1", code: "FAILURE_TYPE_PG" })).toEqual({ kind: "notCompleted" });
  });

  it("code 만 있어도 완료되지 않은 것이다", () => {
    expect(resolvePaymentRedirect({ code: "FAILURE_TYPE_PG" })).toEqual({ kind: "notCompleted" });
  });

  it("아무것도 없으면 결제에서 돌아온 것이 아니다", () => {
    expect(resolvePaymentRedirect({})).toEqual({ kind: "none" });
  });

  it("빈 paymentId 는 없는 것과 같다", () => {
    expect(resolvePaymentRedirect({ paymentId: "" })).toEqual({ kind: "none" });
  });
});
