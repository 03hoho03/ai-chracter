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
