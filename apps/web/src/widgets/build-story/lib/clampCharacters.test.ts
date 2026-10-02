import { describe, expect, it } from "vitest";

import { clampCharacters } from "./clampCharacters";

describe("clampCharacters", () => {
  it("keeps a value within the limit as it is and reports nothing cut", () => {
    expect(clampCharacters("첫 리딩", 20)).toEqual({ value: "첫 리딩", isTruncated: false });
  });

  it("keeps a value exactly at the limit without reporting a cut", () => {
    expect(clampCharacters("가".repeat(20), 20)).toEqual({ value: "가".repeat(20), isTruncated: false });
  });

  it("cuts a pasted value past the limit and reports the cut", () => {
    expect(clampCharacters(`${"가".repeat(19)}!!!`, 20)).toEqual({ value: `${"가".repeat(19)}!`, isTruncated: true });
  });

  it("counts an emoji as one character, the way the server does", () => {
    expect(clampCharacters("😀".repeat(3), 2)).toEqual({ value: "😀😀", isTruncated: true });
    expect(clampCharacters("😀😀", 2).isTruncated).toBe(false);
  });
});
