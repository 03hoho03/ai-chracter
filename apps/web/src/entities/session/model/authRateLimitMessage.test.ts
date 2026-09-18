import { describe, expect, it } from "vitest";

import { formatAuthRateLimitMessage } from "./authRateLimitMessage";

describe("formatAuthRateLimitMessage", () => {
  it.each([
    // 경계값: 0(최소 1분 바닥) · 1 · 59(올림으로 1분) · 60(정확히 1분) · 61(올림 경계, 내림이면 "1분")
    // · 3540(59분) · 3600(BE 시간당 상한 천장, 60분).
    [0, "1분"],
    [1, "1분"],
    [59, "1분"],
    [60, "1분"],
    [61, "2분"],
    [3540, "59분"],
    [3600, "60분"],
  ])("AUTH_LIMIT은 남은 초(%d)를 분으로 올림하되 최소 1분이다", (retryAfterSeconds, expected) => {
    const message = formatAuthRateLimitMessage(
      { code: "AUTH_LIMIT", retryAfterSeconds, window: "auth" },
      "signup",
    );

    expect(message).toContain(expected);
  });

  it("AUTH_COOLDOWN은 분을 말하지 않는다 — 60초 쿨다운은 컴포넌트가 초 단위로 직접 카운트다운한다", () => {
    const message = formatAuthRateLimitMessage(
      { code: "AUTH_COOLDOWN", retryAfterSeconds: 47, window: "auth" },
      "resend",
    );

    expect(message).not.toContain("분");
  });

  it.each(["signup", "password-reset", "resend"] as const)(
    "%s 문구는 계정 존재를 암시하는 어휘를 쓰지 않는다",
    (surface) => {
      const message = formatAuthRateLimitMessage(
        { code: "AUTH_LIMIT", retryAfterSeconds: 60, window: "auth" },
        surface,
      );

      expect(message).not.toContain("계정");
      expect(message).not.toContain("등록");
      expect(message).not.toContain("가입된");
    },
  );
});
