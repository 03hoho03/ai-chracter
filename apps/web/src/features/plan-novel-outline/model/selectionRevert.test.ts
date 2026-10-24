import { describe, expect, it } from "vitest";

import { toSelectionRevert } from "./selectionRevert";

const basis = [{ startMessageId: "u2", endMessageId: "a2" }];

function section(startMessageId: string, endMessageId: string, sourceChanged = false) {
  return {
    startMessageId,
    endMessageId,
    startMessageCreatedAt: "2026-10-24T00:00:01Z",
    endMessageCreatedAt: "2026-10-24T00:00:02.000005Z",
    mode: "include" as const,
    assistantMessageCount: 1,
    sourceChanged,
  };
}

describe("toSelectionRevert", () => {
  it("구성안이 쓴 담기 구간이 실렸고 원문이 그대로면 그 구간으로 정확히 되돌린다", () => {
    const sections = [section("u1", "a2"), section("u5", "a6")];
    expect(toSelectionRevert({ episodes: [{ basis }], sourceSections: sections })).toEqual({
      kind: "exact",
      ranges: sections,
    });
  });

  it("구간 하나라도 원문이 바뀌었으면 되돌려도 낡음이 풀리지 않는다", () => {
    expect(
      toSelectionRevert({ episodes: [{ basis }], sourceSections: [section("u1", "a2"), section("u5", "a6", true)] }),
    ).toEqual({ kind: "sourceChanged" });
  });

  // 서버 이미지를 담기 구간 칸이 생기기 전으로 되돌린 동안에는 칸이 없다 — 화들의 근거로 어림한다.
  it("담기 구간이 없으면(칸이 없거나 null) 화들의 근거로 어림한다", () => {
    const later = { startMessageId: "u4", endMessageId: "a4" };
    const episodes = [{ basis }, { basis: [later] }];
    expect(toSelectionRevert({ episodes })).toEqual({ kind: "approximate", ranges: [...basis, later] });
    expect(toSelectionRevert({ episodes, sourceSections: null })).toEqual({ kind: "approximate", ranges: [...basis, later] });
  });
});
