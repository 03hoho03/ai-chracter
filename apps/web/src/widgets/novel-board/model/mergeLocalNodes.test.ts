import { describe, expect, it } from "vitest";

import { BATCH_FRAME_LABEL_HEIGHT, BATCH_FRAME_PADDING, type BoardNode } from "./boardNode";
import { testBatch, testEpisode, testModel } from "./boardTestModel";
import { layoutBoard } from "./layoutBoard";
import { mergeLocalNodes } from "./mergeLocalNodes";

const model = testModel({
  batches: [testBatch("b1", 1)],
  episodes: [testEpisode("e1", "b1", 1), testEpisode("e2", "b1", 2)],
});

function moved(nodes: BoardNode[], id: string, position: { x: number; y: number }): BoardNode[] {
  return nodes.map((node) => (node.id === id ? { ...node, position, measured: { width: 240, height: 120 } } : node));
}

describe("mergeLocalNodes", () => {
  it("옮긴 카드는 새로 계산해도 화면 자리에 남고 잰 크기도 잇는다", () => {
    const current = moved(layoutBoard(model, null).nodes, "episode:e1", { x: 500, y: 40 });
    const next = layoutBoard({ ...model, notes: "새 노트" }, null).nodes;

    const merged = mergeLocalNodes(next, current, model);
    const episode = merged.find((node) => node.id === "episode:e1");

    expect(episode?.position).toEqual({ x: 500, y: 40 });
    expect(episode?.measured).toEqual({ width: 240, height: 120 });
    // 표시 칸은 새 계산 쪽이다.
    expect(merged.find((node) => node.id === "notes")?.data).toEqual({ notes: "새 노트" });
  });

  it("묶음 테두리는 이은 자리를 다시 둘러싼다", () => {
    const current = moved(layoutBoard(model, null).nodes, "episode:e1", { x: 500, y: -400 });
    const merged = mergeLocalNodes(layoutBoard(model, null).nodes, current, model);
    const frame = merged.find((node) => node.type === "batchFrame");

    expect(frame?.position.y).toBe(-400 - BATCH_FRAME_PADDING - BATCH_FRAME_LABEL_HEIGHT);
    expect(merged[0]?.type).toBe("batchFrame");
  });

  it("새로 생긴 노드는 계산한 자리, 사라진 노드는 따라오지 않는다", () => {
    const current = layoutBoard(model, null).nodes;
    const grown = testModel({
      batches: [testBatch("b1", 1)],
      episodes: [testEpisode("e1", "b1", 1), testEpisode("e3", "b1", 3)],
    });
    const next = layoutBoard(grown, null).nodes;

    const merged = mergeLocalNodes(next, current, grown);

    expect(merged.some((node) => node.id === "episode:e2")).toBe(false);
    expect(merged.find((node) => node.id === "episode:e3")?.position).toEqual(
      next.find((node) => node.id === "episode:e3")?.position,
    );
  });
});
