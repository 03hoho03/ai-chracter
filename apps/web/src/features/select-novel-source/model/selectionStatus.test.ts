import { describe, expect, it } from "vitest";

import { hasChangedSource, toSourceSelectionBase, toSourceSelectionStatus } from "./selectionStatus";

type State = Parameters<typeof toSourceSelectionStatus>[0];

function view(revision: number | null, approvedAt: string | null, sourceChanged = false) {
  return {
    revision,
    approvedAt,
    roomEndMessageId: "m9",
    sections: [{ startMessageId: "m1", endMessageId: "m9", mode: "include" as const, assistantMessageCount: 3, sourceChanged }],
  };
}

function state(parts: Partial<State>): State {
  return { approved: null, draft: null, proposal: null, lockedRanges: [], roomEndMessageId: "m9", hasNewMessages: false, ...parts };
}

describe("toSourceSelectionStatus", () => {
  it("저장한 선택이 없으면 저장 전, 초안이 있으면 초안, 승인본뿐이면 승인됨이다", () => {
    expect(toSourceSelectionStatus(state({ proposal: view(null, null) }))).toBe("unsaved");
    expect(toSourceSelectionStatus(state({ draft: view(1, null) }))).toBe("draft");
    expect(toSourceSelectionStatus(state({ approved: view(1, "t") }))).toBe("approved");
  });

  it("승인본 위에 고친 초안이 있으면 초안이다 — 최신 판이 초안이다", () => {
    expect(toSourceSelectionStatus(state({ approved: view(1, "t"), draft: view(2, null) }))).toBe("draft");
  });
});

describe("toSourceSelectionBase", () => {
  it("화면이 고치기 시작할 판은 초안, 없으면 승인본, 없으면 제안이고 기준 리비전은 그 최신 판이다", () => {
    const approved = view(1, "t");
    const draft = view(2, null);
    const proposal = view(null, null);
    expect(toSourceSelectionBase(state({ approved, draft }))).toEqual({ view: draft, baseRevision: 2 });
    expect(toSourceSelectionBase(state({ approved }))).toEqual({ view: approved, baseRevision: 1 });
    expect(toSourceSelectionBase(state({ proposal }))).toEqual({ view: proposal, baseRevision: null });
  });

  it("셋 다 없으면(받은 응답이 어긋났을 때) 판이 없다", () => {
    expect(toSourceSelectionBase(state({}))).toBeUndefined();
  });
});

describe("hasChangedSource", () => {
  it("구간 하나라도 원문이 바뀌었으면 참이다", () => {
    expect(hasChangedSource(view(1, null))).toBe(false);
    expect(hasChangedSource(view(1, null, true))).toBe(true);
  });
});
