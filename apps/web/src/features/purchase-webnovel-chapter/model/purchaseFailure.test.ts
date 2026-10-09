import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { toPurchaseFailure } from "./purchaseFailure";

function apiError(status: number, detail: Record<string, unknown> | undefined) {
  return new ApiErrorObject({ status, detail, message: "" });
}

describe("toPurchaseFailure", () => {
  it("reads a clover shortage from the novel-read 429", () => {
    expect(
      toPurchaseFailure(apiError(429, { code: "CLOVER_REQUIRED", retryAfterSeconds: 60, window: "novel_read" })),
    ).toEqual({ kind: "insufficient" });
  });

  it("carries the current price when the price moved under the open dialog", () => {
    expect(toPurchaseFailure(apiError(409, { code: "NOVEL_READ_PRICE_CHANGED", currentPrice: 40 }))).toEqual({
      kind: "priceChanged",
      currentPrice: 40,
    });
  });

  it("tells a chapter with nothing to buy apart from other conflicts", () => {
    expect(toPurchaseFailure(apiError(409, { code: "NOVEL_CHAPTER_NOT_FOR_SALE" }))).toEqual({ kind: "notForSale" });
    expect(toPurchaseFailure(apiError(409, { code: "NOVEL_READ_PRICE_CHANGED" }))).toEqual({ kind: "failed" });
  });

  it("treats a vanished chapter as missing and everything else as retryable", () => {
    expect(toPurchaseFailure(apiError(404, { code: "NOVEL_CHAPTER_NOT_FOUND" }))).toEqual({ kind: "missing" });
    expect(toPurchaseFailure(apiError(500, undefined))).toEqual({ kind: "failed" });
    expect(toPurchaseFailure(new Error("network"))).toEqual({ kind: "failed" });
  });
});
