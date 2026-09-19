import { describe, expect, it } from "vitest";

import { getRateLimitDetail } from "./rateLimit";

/** 케이스 구성은 `entities/legal/model/isLegalReconsentRequiredError.test.ts`를 그대로 따른다 —
 * 같은 모양의 429/403 판별이고, 갈리는 지점(상태코드·detail이 string·다른 code)도 같다. */
describe("getRateLimitDetail", () => {
  it("429 + 채팅 USER_LIMIT 바디를 그대로 파싱한다", () => {
    expect(
      getRateLimitDetail({
        status: 429,
        detail: { code: "USER_LIMIT", retryAfterSeconds: 42, window: "minute" },
        message: "x",
      }),
    ).toEqual({ code: "USER_LIMIT", retryAfterSeconds: 42, window: "minute" });
  });

  it("429 + 이미지 QUEUE_FULL 바디를 파싱한다", () => {
    expect(
      getRateLimitDetail({
        status: 429,
        detail: { code: "QUEUE_FULL", retryAfterSeconds: 60, window: "image" },
        message: "x",
      }),
    ).toEqual({ code: "QUEUE_FULL", retryAfterSeconds: 60, window: "image" });
  });

  // T4(error-delivery-goal-prompt.md §5-1, ED-15) — auth 429(4224ea1) 바디 2종도 같은 스키마로
  // 그대로 파싱된다. 전용 파서를 따로 두지 않는 근거이므로, 값이 그대로 돌아오는지가 신호다.
  // 🔴 clover-goal-prompt.md CL-19 — 1관문이 이 값을 모르면 `safeParse`가 실패해 `null`이
  // 되고, 화면은 **429인 줄도 모른 채** 일반 오류로 떨어져 확인 모달이 영원히 안 뜬다.
  // 이 계약은 코드젠을 타지 않아(`openapi.json`의 429 선언 0개) 이 테스트가 유일한 방어다.
  it("429 + CLOVER_CONFIRM_REQUIRED 바디를 파싱한다", () => {
    expect(
      getRateLimitDetail({
        status: 429,
        detail: { code: "CLOVER_CONFIRM_REQUIRED", retryAfterSeconds: 3600, window: "clover" },
        message: "x",
      }),
    ).toEqual({ code: "CLOVER_CONFIRM_REQUIRED", retryAfterSeconds: 3600, window: "clover" });
  });

  it("429 + 이미지의 CLOVER_CONFIRM_REQUIRED 바디도 같은 스키마로 파싱한다", () => {
    expect(
      getRateLimitDetail({
        status: 429,
        detail: { code: "CLOVER_CONFIRM_REQUIRED", retryAfterSeconds: 120, window: "image" },
        message: "x",
      }),
    ).toEqual({ code: "CLOVER_CONFIRM_REQUIRED", retryAfterSeconds: 120, window: "image" });
  });

  it("429 + auth AUTH_LIMIT 바디를 파싱한다", () => {
    expect(
      getRateLimitDetail({
        status: 429,
        detail: { code: "AUTH_LIMIT", retryAfterSeconds: 3540, window: "auth" },
        message: "x",
      }),
    ).toEqual({ code: "AUTH_LIMIT", retryAfterSeconds: 3540, window: "auth" });
  });

  it("429 + auth AUTH_COOLDOWN 바디를 파싱한다", () => {
    expect(
      getRateLimitDetail({
        status: 429,
        detail: { code: "AUTH_COOLDOWN", retryAfterSeconds: 47, window: "auth" },
        message: "x",
      }),
    ).toEqual({ code: "AUTH_COOLDOWN", retryAfterSeconds: 47, window: "auth" });
  });

  // T-21(clover-techspec.md CT-8) — 클로버 부족 429. 채팅은 신규 `window: "clover"`를 쓰고
  // 이미지는 기존 `"image"`를 유지하되 `code`로 갈린다(BE `core/rate_limit_gate.py`의
  // `_CLOVER_CODE`/`_CLOVER_WINDOW`). 🔴 이 스키마가 1관문이라 여기서 막히면 `safeParse`가
  // 실패해 `getRateLimitDetail`이 null을 돌려주고 **429인 줄도 모른 채** 일반 오류로 떨어진다.
  it("429 + 채팅 CLOVER_REQUIRED 바디를 파싱한다", () => {
    expect(
      getRateLimitDetail({
        status: 429,
        detail: { code: "CLOVER_REQUIRED", retryAfterSeconds: 12345, window: "clover" },
        message: "x",
      }),
    ).toEqual({ code: "CLOVER_REQUIRED", retryAfterSeconds: 12345, window: "clover" });
  });

  it("429 + 이미지 CLOVER_REQUIRED 바디를 파싱한다 — window는 image를 유지한다", () => {
    expect(
      getRateLimitDetail({
        status: 429,
        detail: { code: "CLOVER_REQUIRED", retryAfterSeconds: 3600, window: "image" },
        message: "x",
      }),
    ).toEqual({ code: "CLOVER_REQUIRED", retryAfterSeconds: 3600, window: "image" });
  });

  it("429여도 detail이 string이면 null이다 — 구조화 dict를 쓰지 않는 429와 구분돼야 한다", () => {
    expect(getRateLimitDetail({ status: 429, detail: "Too Many Requests", message: "x" })).toBeNull();
  });

  it("429 + 모르는 code면 null이다", () => {
    expect(
      getRateLimitDetail({
        status: 429,
        detail: { code: "다른값", retryAfterSeconds: 10, window: "minute" },
        message: "x",
      }),
    ).toBeNull();
  });

  it.each([400, 403, 500])("같은 detail이어도 상태코드가 429가 아니면(%d) null이다", (status) => {
    expect(
      getRateLimitDetail({
        status,
        detail: { code: "USER_LIMIT", retryAfterSeconds: 10, window: "minute" },
        message: "x",
      }),
    ).toBeNull();
  });

  it("retryAfterSeconds가 없으면 null이다 — 카운트다운을 만들 수 없다", () => {
    expect(
      getRateLimitDetail({ status: 429, detail: { code: "USER_LIMIT", window: "minute" }, message: "x" }),
    ).toBeNull();
  });
});
