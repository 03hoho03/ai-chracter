import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { MEDIA_BOOK_POSITION_TAKEN_MESSAGE, storyAutosaveErrorMessage } from "./mediaBookSaveError";

describe("storyAutosaveErrorMessage", () => {
  it("explains the media book position conflict so the user reloads instead of waiting", () => {
    const error = new ApiErrorObject({
      status: 409,
      message: "conflict",
      detail: { code: "MEDIA_BOOK_CELL_POSITION_TAKEN" },
    });

    expect(storyAutosaveErrorMessage(error)).toBe(MEDIA_BOOK_POSITION_TAKEN_MESSAGE);
  });

  it("falls back to the default message for other failures", () => {
    expect(storyAutosaveErrorMessage(new ApiErrorObject({ status: 409, message: "x", detail: { code: "OTHER" } }))).toBeUndefined();
    expect(storyAutosaveErrorMessage(new ApiErrorObject({ status: 500, message: "x", detail: "boom" }))).toBeUndefined();
    expect(storyAutosaveErrorMessage(new Error("network"))).toBeUndefined();
  });
});
