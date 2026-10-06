import { describe, expect, it } from "vitest";

import { toRevisionSourceLabel } from "./revisionLabel";

const revisions = [
  { id: "r3", revisionNo: 3 },
  { id: "r1", revisionNo: 1 },
];

describe("toRevisionSourceLabel", () => {
  it("되돌린 판은 어느 판에서 왔는지 번호로 말한다", () => {
    expect(toRevisionSourceLabel({ source: "revert", revertedFromRevisionId: "r1" }, revisions)).toBe("1판으로 되돌림");
  });

  it("되돌린 원래 판을 목록에서 못 찾으면 번호 없이 말한다", () => {
    expect(toRevisionSourceLabel({ source: "revert", revertedFromRevisionId: "gone" }, revisions)).toBe(
      "옛 판으로 되돌림",
    );
  });

  it("되돌림 밖의 출처는 고정 문구다", () => {
    expect(toRevisionSourceLabel({ source: "ai_edit", revertedFromRevisionId: null }, revisions)).toBe("AI로 고침");
    expect(toRevisionSourceLabel({ source: "generate", revertedFromRevisionId: null }, revisions)).toBe("처음 만듦");
  });
});
