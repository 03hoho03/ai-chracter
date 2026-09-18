import { describe, expect, it } from "vitest";

import { formatImageRateLimitMessage } from "./imageRateLimitMessage";

describe("formatImageRateLimitMessage", () => {
  it.each([
    // count 상한 2 × 충전 3600초가 retryAfterSeconds의 천장이다(BE take_tokens).
    [7200, "120분"],
    [3600, "60분"],
    [90, "2분"],
    // 61초는 올림(2분)과 반올림(1분)이 갈리는 지점이다 — 없으면 둘 중 무엇이든 통과한다.
    [61, "2분"],
    [20, "1분"],
  ])("USER_LIMIT은 남은 초(%d)를 분으로 올림하되 최소 1분이다", (retryAfterSeconds, expected) => {
    const message = formatImageRateLimitMessage({ code: "USER_LIMIT", retryAfterSeconds, window: "image" });

    expect(message).toContain(expected);
  });

  it("USER_LIMIT은 '한 장'을 약속하지 않는다 — 이 초는 요청한 장수를 다시 살 수 있게 되는 시각이다", () => {
    const message = formatImageRateLimitMessage({ code: "USER_LIMIT", retryAfterSeconds: 6120, window: "image" });

    expect(message).not.toContain("한 장");
    expect(message).toContain("다시 시도");
  });

  it("QUEUE_FULL은 USER_LIMIT과 다른 문구다 — 상한에 닿은 것과 큐가 찬 것은 다음 행동이 다르다", () => {
    const queueFull = formatImageRateLimitMessage({ code: "QUEUE_FULL", retryAfterSeconds: 60, window: "image" });

    expect(queueFull).not.toBe(
      formatImageRateLimitMessage({ code: "USER_LIMIT", retryAfterSeconds: 60, window: "image" }),
    );
    expect(queueFull).not.toContain("분");
  });
});
