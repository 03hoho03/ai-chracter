import { describe, expect, it } from "vitest";

import { isImageAspectRatio } from "./schema";

describe("isImageAspectRatio", () => {
  it("목록 안 값을 통과시킨다", () => {
    expect(isImageAspectRatio("1:1")).toBe(true);
    expect(isImageAspectRatio("9:16")).toBe(true);
  });

  it("목록 밖 값을 거른다", () => {
    expect(isImageAspectRatio("5:5")).toBe(false);
  });

  it("radix 단일 토글이 재클릭 시 흘려보내는 빈 문자열을 거른다", () => {
    expect(isImageAspectRatio("")).toBe(false);
  });
});
