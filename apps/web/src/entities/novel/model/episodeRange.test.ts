import { describe, expect, it } from "vitest";

import { chaptersInBatch, toBatchRangeLabel, toEpisodeRangeLabel } from "./episodeRange";

describe("toEpisodeRangeLabel", () => {
  it("한 화면 번호 하나다", () => {
    expect(toEpisodeRangeLabel(3, 3)).toBe("3화");
  });

  it("여러 화면 처음과 끝을 잇는다", () => {
    expect(toEpisodeRangeLabel(3, 5)).toBe("3~5화");
  });
});

describe("chaptersInBatch · toBatchRangeLabel", () => {
  const chapters = [
    { id: "c3", batchId: "b2", ordinal: 3 },
    { id: "c1", batchId: "b1", ordinal: 1 },
    { id: "c4", batchId: "b2", ordinal: 4 },
    { id: "c2", batchId: "b1", ordinal: 2 },
  ];

  // 목차 순서가 섞여 와도 범위의 처음·끝이 뒤집히지 않는다.
  it("그 묶음의 화만 번호 순으로 고른다", () => {
    expect(chaptersInBatch(chapters, "b1").map((chapter) => chapter.id)).toEqual(["c1", "c2"]);
    expect(toBatchRangeLabel(chapters, "b2")).toBe("3~4화");
  });

  it("상세에 그 묶음의 화가 없으면 이름을 만들지 않는다", () => {
    expect(toBatchRangeLabel(chapters, "gone")).toBeUndefined();
  });
});
