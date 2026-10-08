import { describe, expect, it } from "vitest";

import { toAdjacentChapters } from "./adjacentChapters";

const chapters = [{ ordinal: 3 }, { ordinal: 1 }, { ordinal: 2 }];

describe("toAdjacentChapters", () => {
  it("화 번호로 바로 앞·뒤 화를 찾는다(목록 순서와 무관)", () => {
    expect(toAdjacentChapters(chapters, 2)).toEqual({ previous: { ordinal: 1 }, next: { ordinal: 3 } });
  });

  it("첫 화는 앞이, 마지막 화는 뒤가 없다", () => {
    expect(toAdjacentChapters(chapters, 1)).toEqual({ previous: undefined, next: { ordinal: 2 } });
    expect(toAdjacentChapters(chapters, 3)).toEqual({ previous: { ordinal: 2 }, next: undefined });
  });

  it("화가 하나뿐이면 앞뒤가 모두 없다", () => {
    expect(toAdjacentChapters([{ ordinal: 1 }], 1)).toEqual({ previous: undefined, next: undefined });
  });
});
