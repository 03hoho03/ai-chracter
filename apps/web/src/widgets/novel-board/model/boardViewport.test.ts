import { describe, expect, it } from "vitest";

import { testBatch, testEpisode, testModel } from "./boardTestModel";
import { isRectInView, toInitialFitNodeIds } from "./boardViewport";
import { layoutBoard } from "./layoutBoard";

describe("toInitialFitNodeIds", () => {
  it("마지막 묶음 셋의 화와 노트에 맞춘다", () => {
    const model = testModel({
      batches: [1, 2, 3, 4].map((ordinal) => testBatch(`b${ordinal}`, ordinal)),
      episodes: [1, 2, 3, 4].map((ordinal) => testEpisode(`e${ordinal}`, `b${ordinal}`, ordinal)),
    });
    const ids = toInitialFitNodeIds(layoutBoard(model, null).nodes, model).map((node) => node.id);

    expect(ids).toEqual(["notes", "episode:e2", "episode:e3", "episode:e4"]);
  });

  it("묶음 순서는 배열 순서가 아니라 번호다", () => {
    const model = testModel({
      batches: [testBatch("b4", 4), testBatch("b1", 1), testBatch("b3", 3), testBatch("b2", 2)],
      episodes: [testEpisode("e1", "b1", 1), testEpisode("e4", "b4", 4)],
    });
    const ids = toInitialFitNodeIds(layoutBoard(model, null).nodes, model).map((node) => node.id);

    expect(ids).toEqual(["notes", "episode:e4"]);
  });

  it("화가 없으면 노트만이다", () => {
    const model = testModel({});
    expect(toInitialFitNodeIds(layoutBoard(model, null).nodes, model)).toEqual([{ id: "notes" }]);
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
