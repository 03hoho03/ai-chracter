import { describe, expect, it } from "vitest";

import { shouldConfirmDraftDiscardOnHistory } from "./draftHistoryBlock";

const SAME = { currentPathname: "/novels/a", nextPathname: "/novels/a" };

describe("shouldConfirmDraftDiscardOnHistory", () => {
  it("고치던 글이 있을 때 같은 소설 안의 뒤로는 확인을 받는다", () => {
    expect(shouldConfirmDraftDiscardOnHistory({ ...SAME, action: "BACK", isDraftDirty: true })).toBe(true);
  });

  it.each(["FORWARD", "GO"] as const)("%s 는 막지 않는다(막으면 라우터가 앞으로 한 칸 더 가 주소와 화면이 어긋난다)", (action) => {
    expect(shouldConfirmDraftDiscardOnHistory({ ...SAME, action, isDraftDirty: true })).toBe(false);
  });

  it("고치던 글이 없으면 막지 않는다", () => {
    expect(shouldConfirmDraftDiscardOnHistory({ ...SAME, action: "BACK", isDraftDirty: false })).toBe(false);
  });

  it.each(["PUSH", "REPLACE"] as const)("화면이 스스로 하는 %s 는 막지 않는다(장 이동은 그 자리에서 이미 확인한다)", (action) => {
    expect(shouldConfirmDraftDiscardOnHistory({ ...SAME, action, isDraftDirty: true })).toBe(false);
  });

  it("다른 화면으로 가는 뒤로는 막지 않는다", () => {
    expect(
      shouldConfirmDraftDiscardOnHistory({
        currentPathname: "/novels/a",
        nextPathname: "/novels",
        action: "BACK",
        isDraftDirty: true,
      }),
    ).toBe(false);
  });
});
