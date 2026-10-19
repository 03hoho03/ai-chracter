import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "../client";

import { isPixelLimitRejection } from "./uploadAsset";

function rejection(status: number, detail: ApiErrorObject["detail"]): ApiErrorObject {
  return new ApiErrorObject({ status, message: "", detail });
}

describe("isPixelLimitRejection", () => {
  it("is true only for the 400 that carries the pixel limit", () => {
    expect(isPixelLimitRejection(rejection(400, { maxPixels: 100, actualPixels: 120 }))).toBe(true);
  });

  it("is false for the other upload completion failures", () => {
    expect(isPixelLimitRejection(rejection(400, { maxBytes: 5, actualBytes: 6 }))).toBe(false);
    expect(isPixelLimitRejection(rejection(400, "Uploaded object is not a decodable image"))).toBe(false);
    expect(isPixelLimitRejection(rejection(500, { maxPixels: 1 }))).toBe(false);
    expect(isPixelLimitRejection(new Error("boom"))).toBe(false);
  });
});
