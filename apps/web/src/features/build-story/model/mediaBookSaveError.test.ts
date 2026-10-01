import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import {
  MEDIA_BOOK_POSITION_TAKEN_MESSAGE,
  STORY_SAVE_LIMIT_MESSAGE,
  storyAutosaveErrorMessage,
} from "./mediaBookSaveError";

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
    expect(storyAutosaveErrorMessage(new ApiErrorObject({ status: 0, message: "Network Error", detail: undefined }))).toBeUndefined();
    expect(storyAutosaveErrorMessage(new Error("network"))).toBeUndefined();
  });

  it("tells the user to shorten something on a 422 instead of asking them to wait", () => {
    // 422 본문은 어느 필드가 넘쳤는지 화면이 가려 읽을 수 없는 모양이라 상태 코드만 본다.
    const error = new ApiErrorObject({ status: 422, message: "Field required", detail: undefined, fields: {} });

    expect(storyAutosaveErrorMessage(error)).toBe(STORY_SAVE_LIMIT_MESSAGE);
    expect(STORY_SAVE_LIMIT_MESSAGE).not.toMatch(/잠시 후/);
  });
});
