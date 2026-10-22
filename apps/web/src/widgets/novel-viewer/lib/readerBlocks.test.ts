import { describe, expect, it } from "vitest";

import type { ViewerIllustration } from "../model/viewerSource";
import { toIllustrationLayoutKey, toReaderBlocks } from "./readerBlocks";

function illustration(overrides: Partial<ViewerIllustration>): ViewerIllustration {
  return {
    paragraphIndex: 0,
    placement: "after",
    order: 0,
    source: "upload",
    url: "https://cdn.example/a.webp",
    width: 768,
    height: 1024,
    withheld: null,
    withheldReason: null,
    ...overrides,
  };
}

/** 블록 목록을 읽기 쉬운 줄로 — 문단은 "p0", 그림은 "키". */
function shapeOf(blocks: ReturnType<typeof toReaderBlocks>): string[] {
  return blocks.map((block) => (block.kind === "paragraph" ? `p${block.index}` : block.key));
}

describe("toReaderBlocks", () => {
  it("is just the paragraphs in order when there are no illustrations", () => {
    expect(shapeOf(toReaderBlocks(3, []))).toEqual(["p0", "p1", "p2"]);
  });

  it("puts a paragraph's before-illustrations ahead of it and after-illustrations behind it, each spot by order", () => {
    const blocks = toReaderBlocks(3, [
      illustration({ paragraphIndex: 1, placement: "after", order: 1, url: "x" }),
      illustration({ paragraphIndex: 1, placement: "before", order: 0 }),
      illustration({ paragraphIndex: 1, placement: "after", order: 0, url: "y" }),
      illustration({ paragraphIndex: 0, placement: "before", order: 0 }),
      illustration({ paragraphIndex: 2, placement: "after", order: 0 }),
    ]);
    expect(shapeOf(blocks)).toEqual(["0-before-0", "p0", "1-before-0", "p1", "1-after-0", "1-after-1", "p2", "2-after-0"]);
    const afterOne = blocks.filter((block) => block.kind === "illustration" && block.key.startsWith("1-after"));
    expect(afterOne.map((block) => (block.kind === "illustration" ? block.illustration.url : undefined))).toEqual(["y", "x"]);
  });

  it("drops an illustration anchored past the last paragraph instead of failing", () => {
    expect(shapeOf(toReaderBlocks(2, [illustration({ paragraphIndex: 2 }), illustration({ paragraphIndex: -1 })]))).toEqual([
      "p0",
      "p1",
    ]);
  });
});

describe("toIllustrationLayoutKey", () => {
  const first = illustration({ paragraphIndex: 1, placement: "before" });
  const base = [first];
  const keyOf = (illustrations: ViewerIllustration[]) => toIllustrationLayoutKey(toReaderBlocks(3, illustrations));

  it("is empty when the chapter has no illustrations", () => {
    expect(keyOf([])).toBe("");
  });

  it("changes when something that sizes a block changes — the page split must be measured again", () => {
    const before = keyOf(base);
    const takenDown = { ...first, withheld: "taken_down" as const, withheldReason: "사유", url: null };
    expect(keyOf([takenDown])).not.toBe(before);
    // 사유 글이 바뀌면 줄 수가 달라 안내 상자 높이가 바뀐다.
    expect(keyOf([{ ...takenDown, withheldReason: "조금 더 긴 다른 사유" }])).not.toBe(keyOf([takenDown]));
    expect(keyOf([{ ...first, width: 1280, height: 720 }])).not.toBe(before);
    expect(keyOf([{ ...first, source: "original" }])).not.toBe(before);
    expect(keyOf([{ ...first, placement: "after" }])).not.toBe(before);
    expect(keyOf([...base, illustration({ paragraphIndex: 2 })])).not.toBe(before);
  });

  it("does not change when only the signed url changes — the box keeps its size", () => {
    expect(keyOf([{ ...first, url: "https://cdn.example/a.webp?sig=2" }])).toBe(keyOf(base));
  });
});
