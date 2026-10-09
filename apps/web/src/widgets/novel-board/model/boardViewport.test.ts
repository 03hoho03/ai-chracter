import { describe, expect, it } from "vitest";

import { EPISODE_NODE_HEIGHT } from "./boardNode";
import { testBatch, testEpisode, testModel } from "./boardTestModel";
import { isRectInView, toInitialFitNodeIds } from "./boardViewport";
import { layoutBoard } from "./layoutBoard";

function fitIds(model: ReturnType<typeof testModel>) {
  return toInitialFitNodeIds(layoutBoard(model, null).nodes, model).map((node) => node.id);
}

/** 맞춤 상자의 세로 길이 — 첫 화면이 이 높이를 담는다. */
function fitHeight(model: ReturnType<typeof testModel>) {
  const { nodes } = layoutBoard(model, null);
  const ids = new Set(toInitialFitNodeIds(nodes, model).map((node) => node.id));
  const ys = nodes.filter((node) => ids.has(node.id)).map((node) => node.position.y);
  return Math.max(...ys) + EPISODE_NODE_HEIGHT - Math.min(...ys);
}

/** 묶음마다 화 `perBatch` 개인 소설. */
function novelOf(batchCount: number, perBatch: number) {
  const batches = Array.from({ length: batchCount }, (_, index) => testBatch(`b${index + 1}`, index + 1));
  const episodes = batches.flatMap((batch, batchIndex) =>
    Array.from({ length: perBatch }, (_, index) => {
      const ordinal = batchIndex * perBatch + index + 1;
      return testEpisode(`e${ordinal}`, batch.id, ordinal);
    }),
  );
  return testModel({ batches, episodes });
}

describe("toInitialFitNodeIds", () => {
  it("한 화짜리 묶음이면 마지막 묶음 셋의 화에 맞추고 노트는 넣지 않는다", () => {
    expect(fitIds(novelOf(4, 1))).toEqual(["episode:e2", "episode:e3", "episode:e4"]);
  });

  it("화가 많은 소설도 맞춤 상자가 끝 쪽 몇 장뿐이다(노트가 맨 위라 넣으면 처음부터 끝까지가 된다)", () => {
    const model = novelOf(8, 5);
    expect(fitIds(model)).toEqual(["episode:e36", "episode:e37", "episode:e38", "episode:e39", "episode:e40"]);
    // 900px 높이 캔버스에 배율 1 이하로 다 들어가는 높이다(5장 ≈ 696px).
    expect(fitHeight(model)).toBeLessThan(900);
  });

  it("화 수 상한을 넘기 전까지만 앞 묶음을 더한다", () => {
    expect(fitIds(novelOf(5, 2))).toEqual(["episode:e7", "episode:e8", "episode:e9", "episode:e10"]);
  });

  it("묶음 순서는 배열 순서가 아니라 번호다", () => {
    const model = testModel({
      batches: [testBatch("b4", 4), testBatch("b1", 1), testBatch("b3", 3), testBatch("b2", 2)],
      episodes: [testEpisode("e1", "b1", 1), testEpisode("e4", "b4", 4)],
    });
    expect(fitIds(model)).toEqual(["episode:e1", "episode:e4"]);
  });

  it("화가 없으면 노트만이다", () => {
    expect(fitIds(testModel({}))).toEqual(["notes"]);
  });
});

describe("isRectInView", () => {
  const size = { width: 800, height: 600 };
  const card = { x: 100, y: 100, width: 240, height: 120 };

  it("화면 안이면 참", () => {
    expect(isRectInView(card, { x: 0, y: 0, zoom: 1 }, size)).toBe(true);
  });

  it("조금이라도 밖이면 거짓", () => {
    expect(isRectInView(card, { x: 0, y: -150, zoom: 1 }, size)).toBe(false);
    expect(isRectInView(card, { x: 500, y: 0, zoom: 1 }, size)).toBe(false);
  });

  it("배율을 반영한다", () => {
    expect(isRectInView(card, { x: 0, y: 0, zoom: 3 }, size)).toBe(false);
    expect(isRectInView({ ...card, y: 1100 }, { x: 0, y: 0, zoom: 0.5 }, size)).toBe(false);
    expect(isRectInView({ ...card, y: 900 }, { x: 0, y: 0, zoom: 0.5 }, size)).toBe(true);
  });

  it("화면 크기를 모르면 보인다고 본다", () => {
    expect(isRectInView(card, { x: 0, y: -5000, zoom: 1 }, { width: 0, height: 0 })).toBe(true);
  });
});
