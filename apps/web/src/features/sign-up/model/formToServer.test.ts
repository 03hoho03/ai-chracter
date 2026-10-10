import { describe, expect, it } from "vitest";

import { toSignupRequest, toSocialOnboardingRequest } from "./formToServer";
import { signUpDefaultValues, type SignUpFormValues } from "./signUpSchema";

function valuesWith(personaName: string): SignUpFormValues {
  return {
    ...signUpDefaultValues,
    email: "user@example.com",
    password: "password123",
    nickname: "닉네임",
    birthDate: "2000-01-01",
    termsAgreed: true,
    privacyAgreed: true,
    transferAgreed: true,
    personaName,
  };
}

// 이메일 가입과 소셜 온보딩이 같은 규칙으로 첫 대화 프로필 이름을 싣는다.
describe.each([
  ["toSignupRequest", toSignupRequest],
  ["toSocialOnboardingRequest", toSocialOnboardingRequest],
] as const)("%s personaName", (_label, toRequest) => {
  // 비워 두면 필드째 빠져 서버가 프로필을 만들지 않는다 — 닉네임으로 채우지도 않는다.
  it.each(["", "   "])("omits a blank name %j", (personaName) => {
    expect(toRequest(valuesWith(personaName))).not.toHaveProperty("personaName");
  });

  it("sends the trimmed name", () => {
    expect(toRequest(valuesWith("  지훈 "))).toMatchObject({ personaName: "지훈" });
  });
});
