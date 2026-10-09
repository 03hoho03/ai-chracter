import { describe, expect, it } from "vitest";

import { pickSelectedNodeKey, toCardEscapeAction } from "./canvasSelection";

const EPISODE = "episode:11111111-2222-3333-4444-555555555555";
const OTHER = "episode:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";

describe("pickSelectedNodeKey", () => {
  it("다른 카드를 끌기 시작할 때 오는 고르기 풀림만으로는 아무것도 고르지 않는다(풀지도 않는다)", () => {
    expect(pickSelectedNodeKey([{ type: "select", id: EPISODE, selected: false }])).toBeUndefined();
  });

  it("다른 카드를 누르면 풀림과 고름이 함께 오고, 고른 쪽을 돌려준다", () => {
    expect(
      pickSelectedNodeKey([
        { type: "select", id: EPISODE, selected: false },
        { type: "select", id: OTHER, selected: true },
      ]),
    ).toBe(OTHER);
  });

  it("위치·크기 변경과 고를 수 없는 노드는 무시한다", () => {
    expect(
      pickSelectedNodeKey([
        { type: "position", id: OTHER },
        { type: "dimensions", id: OTHER },
        { type: "select", id: "batch:x", selected: true },
      ]),
    ).toBeUndefined();
  });
});

describe("toCardEscapeAction", () => {
  it("고른 카드의 Esc 는 고르기를 푼다", () => {
    expect(toCardEscapeAction(EPISODE, EPISODE)).toBe("deselect");
  });

  it("포커스만 있는 카드의 Esc 는 아무것도 하지 않는다(고르지 않는다)", () => {
    expect(toCardEscapeAction(OTHER, EPISODE)).toBe("ignore");
    expect(toCardEscapeAction(OTHER, undefined)).toBe("ignore");
  });
});
