import { describe, expect, it } from "vitest";

import { formatChatRateLimitMessage, getChatRateLimit } from "./chatRateLimit";

describe("getChatRateLimit", () => {
  it.each(["minute", "day"] as const)("채팅 창(%s)은 좁혀진 값으로 돌려준다", (window) => {
    expect(
      getChatRateLimit({
        status: 429,
        detail: { code: "USER_LIMIT", retryAfterSeconds: 7, window },
        message: "x",
      }),
    ).toEqual({ window, retryAfterSeconds: 7 });
  });

  it("이미지 창은 undefined다 — 채팅 배너는 minute/day 두 문구만 갖는다", () => {
    expect(
      getChatRateLimit({
        status: 429,
        detail: { code: "USER_LIMIT", retryAfterSeconds: 7, window: "image" },
        message: "x",
      }),
    ).toBeUndefined();
  });

  // T3(error-delivery-goal-prompt.md §5-1) — auth 창도 undefined다. 이 케이스는 런타임 신호가 아니라
  // 타입 신호였다: `getChatRateLimit`이 배제 목록(`window === "image"`만 걸러 undefined)이던 동안은
  // `window` enum에 `"auth"`를 더하는 순간 `ChatRateLimit["window"]`(`"minute" | "day"`)에 안 들어가
  // *컴파일이 안 됐다*(단언 실패가 아니라 타입 에러, 실측: `chatRateLimit.ts(14,12): error TS2322`).
  // 허용 목록(minute/day만 통과)으로 뒤집은 지금은 이 케이스가 평범한 런타임 단언으로 통과한다.
  it("auth 창도 undefined다 — 배제 목록이던 동안은 이 케이스가 타입 에러였다(ED-16)", () => {
    expect(
      getChatRateLimit({
        status: 429,
        detail: { code: "AUTH_LIMIT", retryAfterSeconds: 3540, window: "auth" },
        message: "x",
      }),
    ).toBeUndefined();
  });
});

describe("formatChatRateLimitMessage", () => {
  it("minute 창은 남은 초를 문구에 넣는다 — 배너의 카운트다운이 이 값을 매초 새로 준다", () => {
    const message = formatChatRateLimitMessage({ window: "minute", retryAfterSeconds: 30 }, "chat", 12);

    expect(message).toContain("12초");
    expect(message).toContain("너무 빠르게");
  });

  it("day 창은 초를 쓰지 않는다 — retryAfterSeconds가 최대 86400이라 초 타이머를 걸지 않는다", () => {
    const message = formatChatRateLimitMessage({ window: "day", retryAfterSeconds: 86400 }, "chat", 86400);

    expect(message).not.toContain("초");
    expect(message).toContain("자정");
  });

  it.each(["minute", "day"] as const)("미리보기는 같은 한도를 쓴다고 먼저 말한다(%s)", (window) => {
    const message = formatChatRateLimitMessage({ window, retryAfterSeconds: 30 }, "preview", 30);

    expect(message).toContain("미리보기도 채팅과 같은 한도를 써요");
  });

  it("같은 창이어도 채팅과 미리보기 문구가 다르다", () => {
    const rateLimit = { window: "minute", retryAfterSeconds: 30 } as const;

    expect(formatChatRateLimitMessage(rateLimit, "chat", 30)).not.toBe(
      formatChatRateLimitMessage(rateLimit, "preview", 30),
    );
  });
});
