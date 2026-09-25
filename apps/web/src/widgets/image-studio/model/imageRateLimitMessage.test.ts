import { describe, expect, it } from "vitest";

import { formatImageRateLimitMessage, getImageRateLimit } from "./imageRateLimitMessage";

// 🔴 이 투영은 **세 자리**를 손으로 열어야 한다(유니언 `:8` · 허용 목록
// `:21` · 포매터 `switch`). `:8`을 안 넓히면 나머지 둘도 **컴파일 에러가 안 난다** — 타입이 좁은 채로
// 남아 입력이 조용히 `undefined`로 떨어질 뿐이다. 그래서 투영 자체를 런타임으로 고정한다.
describe("getImageRateLimit", () => {
  it("이미지 CLOVER_REQUIRED를 통과시킨다 — 허용 목록에 없으면 토스트가 아예 안 뜬다", () => {
    expect(
      getImageRateLimit({
        status: 429,
        detail: { code: "CLOVER_REQUIRED", retryAfterSeconds: 3600, window: "image" },
        message: "x",
      }),
    ).toEqual({ code: "CLOVER_REQUIRED", retryAfterSeconds: 3600, window: "image" });
  });

  it("채팅 clover 창은 undefined다 — 이미지 위젯이 받을 429가 아니다", () => {
    expect(
      getImageRateLimit({
        status: 429,
        detail: { code: "CLOVER_REQUIRED", retryAfterSeconds: 43200, window: "clover" },
        message: "x",
      }),
    ).toBeUndefined();
  });
});

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

  // 🔴 이미지 무료분은 **자정이 아니라 시간당 충전**이다(BE
  // `IMAGE_TOKEN_REFILL_SECONDS = 3600`). 채팅 문구("자정에 무료 한도가 돌아와요")를 그대로 옮기면
  // **최대 24시간짜리 거짓말**이 된다. 이미지의 `retryAfterSeconds`는 `take_tokens`가 준 참값이라
  // 그걸 쓰거나 시점을 약속하지 않는 문구를 쓴다.
  it("CLOVER_REQUIRED는 자정을 말하지 않는다 — 이미지는 시간당 충전이라 거짓이 된다", () => {
    const message = formatImageRateLimitMessage({
      code: "CLOVER_REQUIRED",
      retryAfterSeconds: 3600,
      window: "image",
    });

    expect(message).not.toContain("자정");
    expect(message).toContain("클로버");
  });

  it("CLOVER_REQUIRED는 USER_LIMIT과 다른 문구다 — 토큰이 없는 것과 클로버가 없는 것은 다르다", () => {
    expect(
      formatImageRateLimitMessage({ code: "CLOVER_REQUIRED", retryAfterSeconds: 3600, window: "image" }),
    ).not.toBe(formatImageRateLimitMessage({ code: "USER_LIMIT", retryAfterSeconds: 3600, window: "image" }));
  });
});

/** 🔴 이미지도 같다. 확인 코드는 토스트가 아니라 모달로 끝나므로
 * 투영이 `undefined`를 줘야 하고, 그래야 호출부의 모달 분기가 유일한 처리 경로가 된다. */
describe("getImageRateLimit — 확인 코드", () => {
  it("CLOVER_CONFIRM_REQUIRED는 토스트로 새지 않는다", () => {
    expect(
      getImageRateLimit({
        status: 429,
        detail: { code: "CLOVER_CONFIRM_REQUIRED", retryAfterSeconds: 120, window: "image" },
        message: "x",
      }),
    ).toBeUndefined();
  });

  it("부족(CLOVER_REQUIRED)은 그대로 토스트로 간다 — 짝 테스트", () => {
    expect(
      getImageRateLimit({
        status: 429,
        detail: { code: "CLOVER_REQUIRED", retryAfterSeconds: 120, window: "image" },
        message: "x",
      }),
    ).toEqual({ code: "CLOVER_REQUIRED", retryAfterSeconds: 120, window: "image" });
  });
});
