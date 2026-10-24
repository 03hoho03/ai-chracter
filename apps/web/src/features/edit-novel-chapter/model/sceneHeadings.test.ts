import { describe, expect, it } from "vitest";

import { toSceneHeadings } from "./sceneHeadings";

const BLOCKS = ["b0", "b1", "b2", "b3", "b4"].map((id) => ({ id }));

describe("toSceneHeadings", () => {
  it("장면 경계가 없는 화는 머리줄이 없다", () => {
    expect(toSceneHeadings({ blocks: BLOCKS, scenes: [] }).size).toBe(0);
  });

  it("장면마다 그 첫 문단 자리에 본문 차례로 번호와 제목을 단다", () => {
    const headings = toSceneHeadings({
      blocks: BLOCKS,
      // 응답 차례가 본문 차례와 달라도 본문 차례로 번호를 매긴다.
      scenes: [
        { id: "s2", title: "회랑", blockIds: ["b3", "b4"] },
        { id: "s1", title: "문 앞", blockIds: ["b0", "b1", "b2"] },
      ],
    });
    expect([...headings.entries()]).toEqual([
      [0, { sceneKey: "scene:s1", label: "장면 1 · 문 앞" }],
      [3, { sceneKey: "scene:s2", label: "장면 2 · 회랑" }],
    ]);
  });

  it("제목이 비었으면 번호만 단다", () => {
    const headings = toSceneHeadings({ blocks: BLOCKS, scenes: [{ id: "s1", title: " ", blockIds: ["b0", "b1"] }] });
    expect(headings.get(0)?.label).toBe("장면 1");
  });

  it("블록이 지금 판에 하나도 없는 장면은 건너뛰고 번호를 매기지 않는다", () => {
    const headings = toSceneHeadings({
      blocks: BLOCKS,
      scenes: [
        { id: "s0", title: "사라진 장면", blockIds: ["gone"] },
        { id: "s1", title: "문 앞", blockIds: ["b1", "b2"] },
      ],
    });
    expect([...headings.entries()]).toEqual([[1, { sceneKey: "scene:s1", label: "장면 1 · 문 앞" }]]);
  });
});
