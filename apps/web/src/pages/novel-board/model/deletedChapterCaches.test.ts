import { describe, expect, it } from "vitest";

import { canRemoveDeletedChapterCaches } from "./deletedChapterCaches";

describe("canRemoveDeletedChapterCaches", () => {
  // 지운 직후 상세를 다시 받았어도 화면이 다시 그려지기 전에는 지운 화가 보이는 화다 — 그때 지우면 다시 받아 404 다.
  it("화면이 아직 지운 화를 그리고 있으면 버리지 않는다", () => {
    expect(canRemoveDeletedChapterCaches(["c2", "c3"], "c3")).toBe(false);
  });

  it("화면이 다른 화로 옮겼거나 화가 하나도 없으면 버린다", () => {
    expect(canRemoveDeletedChapterCaches(["c2", "c3"], "c1")).toBe(true);
    expect(canRemoveDeletedChapterCaches(["c1"], undefined)).toBe(true);
  });

  it("버릴 것이 없으면 아무것도 하지 않는다", () => {
    expect(canRemoveDeletedChapterCaches([], "c1")).toBe(false);
  });
});
