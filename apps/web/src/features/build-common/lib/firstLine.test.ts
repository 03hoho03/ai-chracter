import { describe, expect, it } from "vitest";

import { firstLine } from "./firstLine";

describe("firstLine", () => {
  it("keeps only the trimmed first line of multi-line text", () => {
    expect(firstLine("  안녕  \n둘째 줄")).toBe("안녕");
  });

  it("returns an empty string for empty text", () => {
    expect(firstLine("")).toBe("");
  });
});
