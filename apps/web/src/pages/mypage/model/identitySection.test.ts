import { describe, expect, it } from "vitest";

import { getIdentitySection } from "./identitySection";

describe("getIdentitySection", () => {
  it("결제도 게이트도 꺼져 있으면 보이지 않는다", () => {
    expect(getIdentitySection({ identityVerified: false, identityGateEnabled: false }, false)).toEqual({ kind: "hidden" });
  });

  it("결제만 켜져 있으면 보이고 구매만 말한다", () => {
    const section = getIdentitySection({ identityVerified: false, identityGateEnabled: false }, true);
    expect(section.kind).toBe("unverified");
    // 게이트가 꺼져 있으면 무료 대화·미션은 인증 없이도 된다 — 그걸 인증 사유로 말하면 거짓이다.
    expect(section.kind === "unverified" && section.message).not.toContain("무료");
  });

  // 게이트만 먼저 켜는 배포에서 결제 스위치만 보면 미인증 회원이 인증할 길이 없어 게이트가 영구 차단이 된다.
  it("게이트만 켜져 있어도 보이고 무료 혜택을 말한다", () => {
    const section = getIdentitySection({ identityVerified: false, identityGateEnabled: true }, false);
    expect(section.kind).toBe("unverified");
    expect(section.kind === "unverified" && section.message).toContain("무료 대화");
    expect(section.kind === "unverified" && section.message).not.toContain("구매");
  });

  it("둘 다 켜져 있으면 둘 다 말한다", () => {
    const section = getIdentitySection({ identityVerified: false, identityGateEnabled: true }, true);
    expect(section.kind === "unverified" && section.message).toContain("구매");
    expect(section.kind === "unverified" && section.message).toContain("무료 대화");
  });

  it("인증을 마쳤으면 인증됨이다", () => {
    expect(getIdentitySection({ identityVerified: true, identityGateEnabled: true }, true)).toEqual({ kind: "verified" });
  });
});
