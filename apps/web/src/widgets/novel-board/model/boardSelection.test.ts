import { describe, expect, it } from "vitest";

import {
  nodeKeyToSelection,
  parseBoardSelection,
  resolveBoardSelection,
  toBoardSelectValue,
  toSelectedNodeKey,
} from "./boardSelection";

const EPISODE_ID = "11111111-2222-3333-4444-555555555555";
const CHARACTER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";

describe("parseBoardSelection", () => {
  it.each([
    [`episode:${EPISODE_ID}`, { kind: "episode", id: EPISODE_ID }],
    [`character:${CHARACTER_ID}`, { kind: "character", id: CHARACTER_ID }],
    ["notes", { kind: "notes" }],
    ["versions", { kind: "versions" }],
  ])("%s 를 고른 것으로 편다", (value, expected) => {
    expect(parseBoardSelection(value)).toEqual(expected);
  });

  it.each([undefined, "", "episode:", "episode:not-a-uuid", `batch:${EPISODE_ID}`, `episode:${EPISODE_ID}x`, "Notes"])(
    "모르는 꼴 %j 는 고른 것 없음으로 접는다",
    (value) => {
      expect(parseBoardSelection(value)).toBeUndefined();
    },
  );

  it("주소 값으로 되돌리면 같은 값이다", () => {
    for (const value of [`episode:${EPISODE_ID}`, `character:${CHARACTER_ID}`, "notes", "versions"]) {
      const selection = parseBoardSelection(value);
      expect(selection && toBoardSelectValue(selection)).toBe(value);
    }
  });
});

describe("toSelectedNodeKey", () => {
  it("버전 패널과 고른 것 없음은 캔버스에서 고를 노드가 없다", () => {
    expect(toSelectedNodeKey({ kind: "versions" })).toBeUndefined();
    expect(toSelectedNodeKey(undefined)).toBeUndefined();
  });

  it("노드가 있는 것은 노드 키다", () => {
    expect(toSelectedNodeKey({ kind: "episode", id: EPISODE_ID })).toBe(`episode:${EPISODE_ID}`);
    expect(toSelectedNodeKey({ kind: "notes" })).toBe("notes");
  });
});

describe("nodeKeyToSelection", () => {
  it("묶음 테두리 키는 고를 수 없다", () => {
    expect(nodeKeyToSelection(`batch:${EPISODE_ID}`)).toBeUndefined();
  });

  it("노드 키 꼴이 아닌 versions 는 노드에서 오지 않는다", () => {
    expect(nodeKeyToSelection("versions")).toBeUndefined();
  });
});

describe("resolveBoardSelection", () => {
  it("지운 화를 가리키면 고른 것 없음이다", () => {
    expect(resolveBoardSelection({ kind: "episode", id: "gone" }, ["c1"], [])).toBeUndefined();
  });

  it("있는 화는 그대로다", () => {
    expect(resolveBoardSelection({ kind: "episode", id: "c1" }, ["c1"], [])).toEqual({ kind: "episode", id: "c1" });
  });

  it("인물 목록을 아직 못 받았으면 인물은 그대로 두고 기다린다", () => {
    expect(resolveBoardSelection({ kind: "character", id: "p1" }, [], undefined)).toEqual({ kind: "character", id: "p1" });
  });

  it("합쳐 사라진 인물은 고른 것 없음이다", () => {
    expect(resolveBoardSelection({ kind: "character", id: "p1" }, [], ["p2"])).toBeUndefined();
  });

  it("노트·버전은 늘 있다", () => {
    expect(resolveBoardSelection({ kind: "notes" }, [], [])).toEqual({ kind: "notes" });
    expect(resolveBoardSelection({ kind: "versions" }, [], undefined)).toEqual({ kind: "versions" });
  });
});

describe("구성 모드(plan)", () => {
  it("plan 을 고른 것으로 펴고 주소 값으로 되돌리면 같은 값이다", () => {
    const selection = parseBoardSelection("plan");
    expect(selection).toEqual({ kind: "plan" });
    expect(selection && toBoardSelectValue(selection)).toBe("plan");
  });

  it("캔버스 노드가 아니다 — 고를 노드도 없고 노드에서 오지도 않는다", () => {
    expect(toSelectedNodeKey({ kind: "plan" })).toBeUndefined();
    expect(nodeKeyToSelection("plan")).toBeUndefined();
  });

  // 스위치가 꺼졌으면 손으로 친 주소나 옛 링크로도 구성 화면이 열리지 않는다(구성 흐름 조회는 404 다).
  it("구성 흐름을 쓸 수 없으면 고른 것 없음으로 접는다", () => {
    expect(resolveBoardSelection({ kind: "plan" }, [], [], { plan: "off" })).toBeUndefined();
    expect(resolveBoardSelection({ kind: "plan" }, [], [])).toBeUndefined();
  });

  // 스위치를 담은 가격 응답을 받는 동안 개요로 튀었다가 돌아오지 않게 그대로 두고 패널이 기다린다.
  it("쓸 수 있거나 아직 모르면 그대로다", () => {
    expect(resolveBoardSelection({ kind: "plan" }, [], [], { plan: "on" })).toEqual({ kind: "plan" });
    expect(resolveBoardSelection({ kind: "plan" }, [], [], { plan: "loading" })).toEqual({ kind: "plan" });
  });
});
