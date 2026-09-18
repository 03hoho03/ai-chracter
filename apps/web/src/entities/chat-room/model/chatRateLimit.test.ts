import { describe, expect, it } from "vitest";

import { formatChatRateLimitAnnouncement, formatChatRateLimitMessage, getChatRateLimit } from "./chatRateLimit";

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

  // T1(error-delivery-goal-prompt.md §5-1) — 0초에서 "0초 뒤 다시"가 남으면 안 된다(ED-10).
  // 카운트다운이 끝나도 버튼은 aria-disabled=false로 풀려 클릭이 통과하므로(S8-8) 문구도 그 사실을
  // 말해야 한다.
  it("minute 창은 0초에서 카운트다운 대신 즉시 재전송 문구를 쓴다(chat)", () => {
    const message = formatChatRateLimitMessage({ window: "minute", retryAfterSeconds: 30 }, "chat", 0);

    expect(message).not.toContain("0초");
    expect(message).toContain("다시 보낼 수 있어요");
  });

  it("minute 창은 0초에서도 미리보기 리드를 먼저 말한다(preview)", () => {
    const message = formatChatRateLimitMessage({ window: "minute", retryAfterSeconds: 30 }, "preview", 0);

    expect(message).not.toContain("0초");
    expect(message).toContain("다시 보낼 수 있어요");
    expect(message).toContain("미리보기도 채팅과 같은 한도를 써요");
  });
});

describe("formatChatRateLimitAnnouncement", () => {
  // T2(error-delivery-goal-prompt.md §5-1) — ED-7: secondsLeft를 받지 않아 마운트 1회 말고는
  // 뮤테이션이 원리적으로 불가능하다. 숫자가 전혀 없어야 role="alert"가 매초 재발화하지 않는다.
  it("minute 창은 초 숫자 없이 대기 안내만 말한다 — 매초 재발화를 막는 설계다", () => {
    const message = formatChatRateLimitAnnouncement({ window: "minute", retryAfterSeconds: 30 }, "chat");

    expect(message).not.toMatch(/\d/);
    expect(message).toContain("잠시 뒤");
  });

  it("day 창 문구는 formatChatRateLimitMessage와 동일하다 — 사본이 아니다", () => {
    const rateLimit = { window: "day", retryAfterSeconds: 86400 } as const;

    expect(formatChatRateLimitAnnouncement(rateLimit, "chat")).toBe(
      formatChatRateLimitMessage(rateLimit, "chat", 86400),
    );
  });
});
