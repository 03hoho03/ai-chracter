import { describe, expect, it } from "vitest";

import { resolveIdentityRedirect } from "./identityRedirect";

describe("resolveIdentityRedirect", () => {
  it("인증 id 만 있으면 결과 저장을 요청한다", () => {
    expect(resolveIdentityRedirect({ identityVerificationId: "idv1" })).toEqual({
      kind: "complete",
      identityVerificationId: "idv1",
    });
  });

  // 포트원은 실패에도 인증 id 를 붙인다 — code 를 먼저 보지 않으면 취소한 인증을 저장하러 간다.
  it("code 가 있으면 인증 id 가 함께 와도 저장하지 않는다", () => {
    expect(resolveIdentityRedirect({ identityVerificationId: "idv1", code: "FAILURE_TYPE_PG" })).toEqual({
      kind: "notCompleted",
    });
  });

  it("아무것도 없으면 인증에서 돌아온 것이 아니다", () => {
    expect(resolveIdentityRedirect({})).toEqual({ kind: "none" });
  });

  it("빈 인증 id 는 없는 것과 같다", () => {
    expect(resolveIdentityRedirect({ identityVerificationId: "" })).toEqual({ kind: "none" });
  });
});
