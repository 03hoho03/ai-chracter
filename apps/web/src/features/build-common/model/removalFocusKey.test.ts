import { describe, expect, it } from "vitest";

import { pickFocusKeyAfterRemoval } from "./removalFocusKey";

describe("pickFocusKeyAfterRemoval", () => {
  it("다음 항목이 있으면 다음 항목으로 간다", () => {
    expect(pickFocusKeyAfterRemoval(["a", "b", "c"], 1)).toBe("c");
  });

  it("마지막 항목을 지우면 이전 항목으로 간다", () => {
    expect(pickFocusKeyAfterRemoval(["a", "b", "c"], 2)).toBe("b");
  });

  it("하나뿐이면 갈 항목이 없다", () => {
    expect(pickFocusKeyAfterRemoval(["a"], 0)).toBeUndefined();
  });
});
