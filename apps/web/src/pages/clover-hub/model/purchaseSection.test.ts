import { describe, expect, it } from "vitest";

import { getPurchaseSection } from "./purchaseSection";

const member = (purchaseBlockReason: "identity_required" | "age_restricted" | null) =>
  ({ kind: "member", me: { purchaseBlockReason } }) as const;

describe("getPurchaseSection", () => {
  // 결제가 닫혀 있으면 누구도 살 수 없다 — 로그인을 권하면 로그인한 뒤에야 살 수 없다는 것을 안다.
  it.each([{ kind: "pending" }, { kind: "guest" }, member(null)] as const)(
    "결제가 꺼져 있으면 세션과 무관하게 준비 중이다 (%o)",
    (viewer) => {
      expect(getPurchaseSection(false, viewer)).toBe("disabled");
    },
  );

  it("세션을 묻는 중이면 행 모양을 정하지 않는다", () => {
    expect(getPurchaseSection(true, { kind: "pending" })).toBe("pending");
  });

  it("로그인하지 않았으면 로그인으로 이어지는 갈래다", () => {
    expect(getPurchaseSection(true, { kind: "guest" })).toBe("guest");
  });

  it("살 수 있으면 상품을 고를 수 있다", () => {
    expect(getPurchaseSection(true, member(null))).toBe("products");
  });

  it("본인인증 전이면 인증 안내다", () => {
    expect(getPurchaseSection(true, member("identity_required"))).toBe("identityRequired");
  });

  // 인증된 미성년에게 상품을 열면 다이얼로그를 다 채운 뒤에야 나이 거절을 받는다.
  it("만 19세 미만이면 나이 안내다", () => {
    expect(getPurchaseSection(true, member("age_restricted"))).toBe("ageRestricted");
  });
});
