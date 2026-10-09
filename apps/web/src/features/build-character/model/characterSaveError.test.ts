import { describe, expect, it } from "vitest";

import { BUILDER_SAVE_LIMIT_MESSAGE } from "@/entities/content";
import { ApiErrorObject } from "@/shared/api/client";

import { characterSaveErrorMessage } from "./characterSaveError";

describe("characterSaveErrorMessage", () => {
  it("tells the user to shorten something on a 422 instead of asking them to wait", () => {
    const error = new ApiErrorObject({ status: 422, message: "String too long", detail: undefined, fields: {} });

    expect(characterSaveErrorMessage(error)).toBe(BUILDER_SAVE_LIMIT_MESSAGE);
    expect(BUILDER_SAVE_LIMIT_MESSAGE).not.toMatch(/잠시 후/);
  });

  it("leaves other failures to the default retry message", () => {
    expect(characterSaveErrorMessage(new ApiErrorObject({ status: 500, message: "x", detail: "boom" }))).toBeUndefined();
    expect(characterSaveErrorMessage(new ApiErrorObject({ status: 0, message: "Network Error", detail: undefined }))).toBeUndefined();
    expect(characterSaveErrorMessage(new Error("network"))).toBeUndefined();
  });
});
