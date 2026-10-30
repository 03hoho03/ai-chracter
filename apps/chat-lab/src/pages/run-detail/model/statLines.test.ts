import { describe, expect, it } from "vitest";

import type { StatSeries } from "@/shared/api/client";

import { defaultSlots, lineCandidates, pickSlot, resolveSlots } from "./statLines";

function series(id: string, overrides: Partial<StatSeries> = {}): StatSeries {
  return { id, name: `이름-${id}`, hidden: false, source: "driver", points: [], ...overrides };
}

const FOUR = [series("a"), series("b"), series("c"), series("d")];

describe("lineCandidates", () => {
  it("선을 그을 수 있는 것은 드라이버에서 온 보이는 스탯뿐이다 — 숨김·턴 기록에서만 온 스탯은 따로 그린다", () => {
    const hidden = series("h", { hidden: true, source: "chatTurns" });
    const recordOnly = series("r", { hidden: false, source: "chatTurns" });

    expect(lineCandidates([series("a"), hidden, recordOnly, series("b")]).map((entry) => entry.id)).toEqual(["a", "b"]);
  });
});

describe("defaultSlots", () => {
  it("선 자리는 셋까지이고 계열 순서대로 앞의 셋이다", () => {
    expect(defaultSlots(FOUR)).toEqual(["a", "b", "c"]);
    expect(defaultSlots(FOUR.slice(0, 2))).toEqual(["a", "b"]);
  });
});

describe("pickSlot", () => {
  it("빈 스탯을 고르면 그 자리만 바뀌고 다른 자리의 스탯은 제 색 자리에 남는다", () => {
    expect(pickSlot(["a", "b", "c"], 1, "d")).toEqual(["a", "d", "c"]);
  });

  it("다른 자리에 있는 스탯을 고르면 두 자리를 맞바꾼다 — 한 스탯이 두 자리에 서지 않는다", () => {
    expect(pickSlot(["a", "b", "c"], 0, "c")).toEqual(["c", "b", "a"]);
  });

  it("없는 자리 번호는 무시한다", () => {
    expect(pickSlot(["a", "b", "c"], 3, "d")).toEqual(["a", "b", "c"]);
  });
});

describe("resolveSlots", () => {
  it("고른 적이 없으면 기본 자리", () => {
    expect(resolveSlots(FOUR, undefined)).toEqual(["a", "b", "c"]);
  });

  it("고른 자리가 이 런의 선 후보로 다 있으면 그대로 쓴다", () => {
    expect(resolveSlots(FOUR, ["d", "a", "b"])).toEqual(["d", "a", "b"]);
  });

  it("고른 자리에 이 런에 없는 스탯이 섞이면(다른 런에서 고른 값) 기본 자리로 돌아간다", () => {
    expect(resolveSlots(FOUR, ["d", "x", "b"])).toEqual(["a", "b", "c"]);
    expect(resolveSlots(FOUR, ["d", "a"])).toEqual(["a", "b", "c"]);
  });
});
