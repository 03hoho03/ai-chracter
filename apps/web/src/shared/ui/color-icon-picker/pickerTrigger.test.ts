import { describe, expect, it } from "vitest";

import { triggerAccessibleName } from "./pickerTrigger";

describe("triggerAccessibleName", () => {
  it("고른 값이 있으면 그 값을 말한다", () => {
    expect(triggerAccessibleName("아이콘", "피로", true)).toBe("아이콘: 피로, 바꾸기");
  });

  it("비었으면 고르라고 말하고, 필수면 그것도 말한다", () => {
    expect(triggerAccessibleName("색", undefined, true)).toBe("색 고르기 (필수)");
    expect(triggerAccessibleName("색", undefined, false)).toBe("색 고르기");
  });
});
