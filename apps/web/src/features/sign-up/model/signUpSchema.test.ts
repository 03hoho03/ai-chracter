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
  };
}

function isoDateYearsAgo(years: number): string {
  const date = new Date();
  date.setFullYear(date.getFullYear() - years);
  return date.toISOString().slice(0, 10);
}

describe("signUpSchema", () => {
  // 국외이전 동의는 수집·이용 동의와 구분된 세 번째
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

  // 서버가 진짜 게이트, 이건 위저드 1스텝의 UX 하한이다.
  it("rejects a birth date under the minimum age", () => {
    const result = signUpSchema.safeParse({
      ...validPayload(),
      birthDate: isoDateYearsAgo(13),
    });

    expect(result.success).toBe(false);
  });

  it("accepts a birth date exactly at the minimum age", () => {
    const result = signUpSchema.safeParse({
      ...validPayload(),
      birthDate: isoDateYearsAgo(14),
    });

    expect(result.success).toBe(true);
  });
});
