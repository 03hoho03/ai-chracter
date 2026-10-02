import { describe, expect, it } from "vitest";

import { planCellSelectionScroll } from "./planCellSelectionScroll";

describe("planCellSelectionScroll", () => {
  it("keeps the picked cell and the detail's first action in view when they fit together", () => {
    expect(planCellSelectionScroll({ cellTop: 100, firstActionBottom: 700, availableHeight: 780 })).toBe("both");
  });

  it("puts the detail header first when the cell and the first action cannot fit in one screen", () => {
    expect(planCellSelectionScroll({ cellTop: -300, firstActionBottom: 700, availableHeight: 780 })).toBe("header");
  });

  it("puts the detail header first when only the header would fit with the cell, so the action is not left below the screen", () => {
    // 머리 아래 끝은 600 이라 칸과 머리만 보면 들어가지만, 첫 행동 줄(빈 칸의 이미지 넣기 버튼)이 900 이라 안 들어간다.
    expect(planCellSelectionScroll({ cellTop: 100, firstActionBottom: 900, availableHeight: 780 })).toBe("header");
  });

  it("treats an exact fit as fitting", () => {
    expect(planCellSelectionScroll({ cellTop: 0, firstActionBottom: 780, availableHeight: 780 })).toBe("both");
  });
});
