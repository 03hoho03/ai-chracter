import { describe, expect, it } from "vitest";

import { signUpSchema } from "./signUpSchema";

function validPayload() {
  return {
    email: "user@example.com",
    password: "password123",
    nickname: "닉네임",
    birthDate: "2000-01-01",
    termsAgreed: true,
    privacyAgreed: true,
    transferAgreed: true,
    emailVerificationCode: "123456",
    // guardian은 항상 필수로 선언돼 있어(만 14세 미만 여부와 무관, 스텝 검증은 trigger()가 갈라
    // 준다) 전체 스키마 파싱 테스트에서는 통과시켜 둔다 — 여기서 검증하는 대상이 아니다.
    guardian: { name: "보호자", contact: "010-0000-0000", consentAgreed: true },
  };
}

describe("signUpSchema", () => {
  // legal-revision-goal-prompt.md LR-1·LR-3 — 국외이전 동의는 수집·이용 동의와 구분된 세 번째
  // 필수 필드다. 빠지거나 false면 파싱이 실패해야 한다.
  it("rejects a payload missing transferAgreed", () => {
    const payloadWithoutTransfer: Record<string, unknown> = { ...validPayload() };
    delete payloadWithoutTransfer.transferAgreed;

    const result = signUpSchema.safeParse(payloadWithoutTransfer);

    expect(result.success).toBe(false);
  });

  it("rejects transferAgreed: false", () => {
    const result = signUpSchema.safeParse({ ...validPayload(), transferAgreed: false });

    expect(result.success).toBe(false);
  });

  it("accepts a fully agreed payload", () => {
    const result = signUpSchema.safeParse(validPayload());

    expect(result.success).toBe(true);
  });
});
