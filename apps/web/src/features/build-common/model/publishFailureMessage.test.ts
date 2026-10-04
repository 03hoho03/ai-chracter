import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { getPublishFailureMessage, PUBLISH_SCREENING_UNAVAILABLE_MESSAGE } from "./publishFailureMessage";
import { getFilterRejectionReason } from "./publishRejection";

function apiError(status: number, detail: string | Record<string, unknown> = "x") {
  return new ApiErrorObject({ status, message: "x", detail });
}

describe("getPublishFailureMessage", () => {
  it.each([
    // 경계값: 0(최소 1분 바닥) · 60(정확히 1분) · 61(올림 경계, 내림이면 "1분") · 3600(시간 창 천장).
    [0, "약 1분"],
    [60, "약 1분"],
    [61, "약 2분"],
    [3600, "약 60분"],
  ])("429 publish 창은 남은 초(%d)를 분으로 올림해 말한다", (retryAfterSeconds, expected) => {
    const message = getPublishFailureMessage(
      apiError(429, { code: "USER_LIMIT", retryAfterSeconds, window: "publish" }),
    );

    expect(message).toContain(expected);
    expect(message).toContain("발행 심사 요청이 너무 많았어요");
  });

  // 업로드 429 는 결정상 기존 폴백 문구를 그대로 쓴다 — 발행 문구가 업로드 실패에 새면 안 된다.
  it.each(["upload", "image", "minute"])("다른 창(%s)의 429 는 undefined", (window) => {
    expect(
      getPublishFailureMessage(apiError(429, { code: "USER_LIMIT", retryAfterSeconds: 60, window })),
    ).toBeUndefined();
  });

  it("503 PUBLISH_SCREENING_UNAVAILABLE 은 서버 message 를 그대로 보인다", () => {
    const error = apiError(503, { code: "PUBLISH_SCREENING_UNAVAILABLE", message: "서버가 준 문구" });

    expect(getPublishFailureMessage(error)).toBe("서버가 준 문구");
  });

  it("503 PUBLISH_SCREENING_UNAVAILABLE 에 message 가 없으면 같은 뜻의 기본 문구다", () => {
    const error = apiError(503, { code: "PUBLISH_SCREENING_UNAVAILABLE" });

    expect(getPublishFailureMessage(error)).toBe(PUBLISH_SCREENING_UNAVAILABLE_MESSAGE);
  });

  it.each([
    apiError(503, "Service Unavailable"),
    apiError(503, { code: "OTHER" }),
    apiError(502, { code: "PUBLISH_SCREENING_UNAVAILABLE", message: "x" }),
    apiError(400, { reason: "거부 사유" }),
    new Error("network"),
  ])("심사 단계 실패가 아니면 undefined (%#)", (error) => {
    expect(getPublishFailureMessage(error)).toBeUndefined();
  });

  // 이의제기 진입점은 400 `reason` 으로만 열린다. 심사 호출 실패를 거부로 읽으면 수용해도 바뀌는 게 없는 이의제기로 보낸다.
  it("503 심사 불가는 발행 거부로 분류되지 않는다", () => {
    const error = apiError(503, { code: "PUBLISH_SCREENING_UNAVAILABLE", message: "x" });

    expect(getFilterRejectionReason(error)).toBeUndefined();
  });
});
