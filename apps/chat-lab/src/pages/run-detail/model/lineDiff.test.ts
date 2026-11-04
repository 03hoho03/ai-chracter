import { describe, expect, it } from "vitest";

import { diffLines, foldDiff } from "./lineDiff";

describe("diffLines", () => {
  it("같은 원문이면 모든 줄이 같음", () => {
    expect(diffLines("a\nb", "a\nb")).toEqual([
      { kind: "same", text: "a" },
      { kind: "same", text: "b" },
    ]);
  });

  it("앞 원문에만 있는 줄은 빠짐, 뒤 원문에만 있는 줄은 더함 — 순서는 원문 순서", () => {
    expect(diffLines("a\nb\nc", "a\nx\nc\nd")).toEqual([
      { kind: "same", text: "a" },
      { kind: "removed", text: "b" },
      { kind: "added", text: "x" },
      { kind: "same", text: "c" },
      { kind: "added", text: "d" },
    ]);
  });

  it("빈 원문과 견주면 모든 줄이 더함", () => {
    expect(diffLines("", "a")).toEqual([
      { kind: "removed", text: "" },
      { kind: "added", text: "a" },
    ]);
  });
});

describe("foldDiff", () => {
  it("바뀐 줄 앞뒤 문맥만 남기고 긴 같은 줄 구간을 접는다", () => {
    const before = ["1", "2", "3", "4", "5", "6", "7"].join("\n");
    const after = ["1", "2", "3", "4", "X", "6", "7"].join("\n");

    expect(foldDiff(diffLines(before, after), 1)).toEqual([
      { kind: "folded", count: 3 },
      { kind: "same", text: "4" },
      { kind: "removed", text: "5" },
      { kind: "added", text: "X" },
      { kind: "same", text: "6" },
      { kind: "folded", count: 1 },
    ]);
  });

  it("바뀐 줄이 없으면 한 덩어리로 접는다", () => {
    expect(foldDiff(diffLines("a\nb", "a\nb"), 2)).toEqual([{ kind: "folded", count: 2 }]);
  });
});
