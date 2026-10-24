import { describe, expect, it } from "vitest";

import { toRegenerateSummaryFailure } from "./regenerateSummaryFailure";

function apiError(status: number, detail: unknown) {
  return { status, detail, message: "x" };
}

describe("toRegenerateSummaryFailure", () => {
  it("carries the new price so the dialog can ask again with it", () => {
    expect(
      toRegenerateSummaryFailure(apiError(409, { code: "MEMORY_SUMMARY_REGENERATE_PRICE_CHANGED", currentCost: 20 })),
    ).toEqual({
      kind: "priceChanged",
      currentCost: 20,
      message: "그사이 가격이 바뀌었어요. 바뀐 금액을 확인하고 다시 눌러 주세요.",
    });
  });

  it("leaves the new price unknown when the server did not send a number", () => {
    const failure = toRegenerateSummaryFailure(apiError(409, { code: "MEMORY_SUMMARY_REGENERATE_PRICE_CHANGED" }));
    expect(failure).toMatchObject({ kind: "priceChanged", currentCost: undefined });
  });

  it("says another regeneration of this room is still running", () => {
    expect(toRegenerateSummaryFailure(apiError(409, { code: "MEMORY_SUMMARY_REGENERATE_IN_PROGRESS" }))).toEqual({
      kind: "inProgress",
      message: "이 대화방의 요약을 이미 다시 만들고 있어요. 끝나면 요약이 바뀌어요.",
    });
  });

  it("treats a changed or missing summary as stale, so the memory is fetched again", () => {
    for (const code of ["MEMORY_VERSION_CONFLICT", "MEMORY_SUMMARY_NOT_READY"]) {
      expect(toRegenerateSummaryFailure(apiError(409, { code }))).toEqual({
        kind: "stale",
        message: "그사이 요약이 바뀌었어요. 바뀐 요약을 확인하고 다시 눌러 주세요.",
      });
    }
  });

  it("reads the clover shortage from the memory summary 429", () => {
    expect(
      toRegenerateSummaryFailure(
        apiError(429, { code: "CLOVER_REQUIRED", retryAfterSeconds: 600, window: "memory_summary" }),
      ),
    ).toEqual({ kind: "cloverRequired" });
  });

  it("does not take another feature's clover 429 for this one", () => {
    expect(
      toRegenerateSummaryFailure(apiError(429, { code: "CLOVER_REQUIRED", retryAfterSeconds: 600, window: "clover" })),
    ).toMatchObject({ kind: "message" });
  });

  it("says the clover came back when the summary could not be written", () => {
    expect(toRegenerateSummaryFailure(apiError(503, { code: "MEMORY_SUMMARY_REGENERATE_UNAVAILABLE" }))).toEqual({
      kind: "unavailable",
      message: "요약을 다시 만들지 못했어요. 쓴 클로버는 돌려드렸어요. 잠시 후 다시 시도해 주세요.",
    });
  });

  it("tells the panel the switch was turned off", () => {
    expect(toRegenerateSummaryFailure(apiError(404, { code: "MEMORY_ITEMS_DISABLED" }))).toEqual({
      kind: "disabled",
      message: "지금은 요약을 다시 만들 수 없어요.",
    });
  });

  it("says a restricted work cannot be regenerated", () => {
    expect(toRegenerateSummaryFailure(apiError(403, { code: "CONTENT_RESTRICTED" }))).toEqual({
      kind: "message",
      message: "이용이 제한된 작품이라 요약을 다시 만들 수 없어요.",
    });
  });

  it("falls back to a general sentence that does not promise a refund", () => {
    expect(toRegenerateSummaryFailure(new Error("network"))).toEqual({
      kind: "message",
      message: "요약을 다시 만들지 못했어요. 잠시 후 다시 시도해 주세요.",
    });
  });
});
