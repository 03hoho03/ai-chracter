import { describe, expect, it } from "vitest";

import { planCellSelectionScroll } from "./planCellSelectionScroll";

describe("planCellSelectionScroll", () => {
  it("keeps both the picked cell and the detail header in view when they fit together", () => {
    expect(planCellSelectionScroll({ cellTop: 100, headerBottom: 700, availableHeight: 780 })).toBe("both");
  });

  it("puts the detail header first when the cell and header cannot fit in one screen", () => {
    expect(planCellSelectionScroll({ cellTop: -300, headerBottom: 700, availableHeight: 780 })).toBe("header");
  });

  it("treats an exact fit as fitting", () => {
    expect(planCellSelectionScroll({ cellTop: 0, headerBottom: 780, availableHeight: 780 })).toBe("both");
  });
});
