import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { toWebnovelLoadFailure } from "./webnovelError";

function apiError(status: number, detail: Record<string, unknown> | string | undefined) {
  return new ApiErrorObject({ status, detail, message: "" });
}

describe("toWebnovelLoadFailure", () => {
  it("reads the reason and refunded clovers from an ended-reading 410", () => {
    expect(toWebnovelLoadFailure(apiError(410, { code: "NOVEL_READING_ENDED", reason: "deleted", refundedAmount: 30 }))).toEqual({
      kind: "ended",
      reason: "deleted",
      refundedAmount: 30,
    });
  });

  it("keeps an ended reading but drops a reason it does not know", () => {
    expect(toWebnovelLoadFailure(apiError(410, { code: "NOVEL_READING_ENDED", reason: "moon" }))).toEqual({
      kind: "ended",
      reason: undefined,
      refundedAmount: 0,
    });
  });

  it("folds every 404 into one missing state, including a switched-off service", () => {
    expect(toWebnovelLoadFailure(apiError(404, { code: "NOVEL_NOT_FOUND" }))).toEqual({ kind: "missing" });
    expect(toWebnovelLoadFailure(apiError(404, { code: "NOVEL_PUBLIC_DISABLED" }))).toEqual({ kind: "missing" });
  });

  it("treats other failures as retryable", () => {
    expect(toWebnovelLoadFailure(apiError(500, undefined))).toEqual({ kind: "failed" });
    expect(toWebnovelLoadFailure(apiError(410, { code: "SOMETHING_ELSE" }))).toEqual({ kind: "failed" });
    expect(toWebnovelLoadFailure(new Error("network"))).toEqual({ kind: "failed" });
  });
});
