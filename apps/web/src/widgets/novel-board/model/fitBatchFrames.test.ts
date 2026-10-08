import { describe, expect, it } from "vitest";

import {
  BATCH_FRAME_LABEL_HEIGHT,
  BATCH_FRAME_PADDING,
  EPISODE_NODE_HEIGHT,
  EPISODE_NODE_WIDTH,
  type BoardModel,
  type BoardNode,
  type EpisodeNode,
} from "./boardNode";
import { testBatch, testEpisode, testModel } from "./boardTestModel";
import { fitBatchFrames } from "./fitBatchFrames";

const model: BoardModel = testModel({ batches: [testBatch("b1", 1), testBatch("b-empty", 2)] });

function episode(id: string, x: number, y: number, measured?: { width: number; height: number }): EpisodeNode {
  const { id: episodeId, ...display } = testEpisode(id, "b1", 1);
  return {
    id: `episode:${id}`,
    type: "episode",
    position: { x, y },
    data: { episodeId, ...display },
    ...(measured ? { measured } : {}),
  };
}

function frameOf(nodes: BoardNode[]) {
  const frame = nodes.find((node) => node.type === "batchFrame");
  if (!frame) throw new Error("missing frame");
  return frame;
}

describe("fitBatchFrames", () => {
  it("wraps the bounding box of the batch's episodes with padding and a label row", () => {
    const frame = frameOf(fitBatchFrames([episode("a", 0, 0), episode("b", 100, 300)], model));
    const top = -BATCH_FRAME_PADDING - BATCH_FRAME_LABEL_HEIGHT;
    expect(frame.position).toEqual({ x: -BATCH_FRAME_PADDING, y: top });
    expect(frame.width).toBe(100 + EPISODE_NODE_WIDTH + 2 * BATCH_FRAME_PADDING);
    expect(frame.height).toBe(300 + EPISODE_NODE_HEIGHT + BATCH_FRAME_PADDING - top);
  });

  it("uses the measured card size once the card has been rendered", () => {
    const frame = frameOf(fitBatchFrames([episode("a", 0, 0, { width: 400, height: 50 })], model));
    expect(frame.width).toBe(400 + 2 * BATCH_FRAME_PADDING);
    expect(frame.height).toBe(50 + 2 * BATCH_FRAME_PADDING + BATCH_FRAME_LABEL_HEIGHT);
  });

  it("is a non-interactive background node without a parent link", () => {
    const frame = frameOf(fitBatchFrames([episode("a", 0, 0)], model));
    expect(frame).toMatchObject({ draggable: false, selectable: false, focusable: false, deletable: false });
    expect(frame.parentId).toBeUndefined();
  });

  it("recomputes frames after a move instead of keeping the old ones, and skips batches without episodes", () => {
    const first = fitBatchFrames([episode("a", 0, 0)], model);
    const movedEpisodes = first.map((node) =>
      node.type === "episode" ? { ...node, position: { x: 1000, y: 1000 } } : node,
    );
    const refitted = fitBatchFrames(movedEpisodes, model);
    expect(refitted.filter((node) => node.type === "batchFrame")).toHaveLength(1);
    expect(frameOf(refitted).position.x).toBe(1000 - BATCH_FRAME_PADDING);
    expect(refitted.some((node) => node.id === "batch:b-empty")).toBe(false);
  });

  it("자리·크기가 그대로인 테두리는 같은 객체를 돌려줘 라이브러리가 다시 재지 않게 한다", () => {
    const first = fitBatchFrames([episode("e1", 0, 0)], model);
    const measuredFrame = { ...frameOf(first), measured: { width: 272, height: 176 } };
    const withMeasured = first.map((node) => (node.type === "batchFrame" ? measuredFrame : node));

    const same = fitBatchFrames(withMeasured, model);
    const moved = fitBatchFrames(
      withMeasured.map((node) => (node.type === "episode" ? episode("e1", 50, 0) : node)),
      model,
    );

    expect(frameOf(same)).toBe(measuredFrame);
    expect(frameOf(moved)).not.toBe(measuredFrame);
    expect(frameOf(moved).position.x).toBe(50 - BATCH_FRAME_PADDING);
  });

  it("묶음 테두리는 장식이라 보조기기에서 숨기고 라이브러리의 영어 역할 설명을 지운다", () => {
    expect(frameOf(fitBatchFrames([episode("e1", 0, 0)], model)).domAttributes).toEqual({
      "aria-hidden": true,
      "aria-roledescription": undefined,
    });
  });
});
