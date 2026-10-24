import { describe, expect, it } from "vitest";

import { isOutlineFlowBatch } from "./outlineFlowChapter";

const chapters = [
  { id: "c1", batchId: "b1", ordinal: 1, episodeOutlineId: null },
  { id: "c2", batchId: "b2", ordinal: 2, episodeOutlineId: "eo-2" },
  { id: "c3", batchId: "b3", ordinal: 3, episodeOutlineId: "eo-3" },
  { id: "c4", batchId: "b3", ordinal: 4, episodeOutlineId: null },
];

describe("구성 흐름 묶음", () => {
  it("묶음의 화가 모두 구성안으로 쓴 화일 때만이다", () => {
    expect(isOutlineFlowBatch(chapters, "b1")).toBe(false);
    expect(isOutlineFlowBatch(chapters, "b2")).toBe(true);
    expect(isOutlineFlowBatch(chapters, "b3")).toBe(false);
  });

  it("화가 없는 묶음은 아니다", () => {
    expect(isOutlineFlowBatch(chapters, "b9")).toBe(false);
  });

  it("표지가 없는 옛 응답의 화는 옛 흐름이다", () => {
    expect(isOutlineFlowBatch([{ id: "c1", batchId: "b1", ordinal: 1 }], "b1")).toBe(false);
  });
});
