import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import {
  GENERIC_MEMORY_ERROR_MESSAGE,
  INVALID_MEMORY_INPUT_MESSAGE,
  MEMORY_CONFLICT_MESSAGE,
  MEMORY_NOTHING_TO_REVERT_MESSAGE,
  MEMORY_SUMMARY_NOT_READY_MESSAGE,
  toMemoryWriteError,
} from "./memoryWriteError";

function conflict(code: string) {
  return new ApiErrorObject({ status: 409, detail: { code }, message: "Request failed with status code 409" });
}

describe("toMemoryWriteError", () => {
  // 409는 전부 "화면이 서버보다 낡았다"라 다시 불러오기로 풀린다 — 문구만 코드별로 다르다.
  it.each([
    ["MEMORY_VERSION_CONFLICT", MEMORY_CONFLICT_MESSAGE],
    ["MEMORY_SUMMARY_NOT_READY", MEMORY_SUMMARY_NOT_READY_MESSAGE],
    ["MEMORY_NOTHING_TO_REVERT", MEMORY_NOTHING_TO_REVERT_MESSAGE],
  ])("treats %s as a stale screen", (code, message) => {
    expect(toMemoryWriteError(conflict(code))).toEqual({ kind: "stale", message });
  });

  it("still offers reloading for a 409 with an unknown code", () => {
    expect(toMemoryWriteError(conflict("SOMETHING_NEW"))).toEqual({ kind: "stale", message: MEMORY_CONFLICT_MESSAGE });
  });

  it("never shows the raw 422 message", () => {
    const error = new ApiErrorObject({
      status: 422,
      detail: undefined,
      message: "String should have at most 1000 characters",
      fields: { note: "String should have at most 1000 characters" },
    });
    expect(toMemoryWriteError(error)).toEqual({ kind: "message", message: INVALID_MEMORY_INPUT_MESSAGE });
  });

  it("falls back to the generic copy for other statuses and non-API errors", () => {
    const forbidden = new ApiErrorObject({ status: 403, detail: "Not your room", message: "Not your room" });
    expect(toMemoryWriteError(forbidden)).toEqual({ kind: "message", message: GENERIC_MEMORY_ERROR_MESSAGE });
    expect(toMemoryWriteError(new Error("network"))).toEqual({ kind: "message", message: GENERIC_MEMORY_ERROR_MESSAGE });
  });
});
