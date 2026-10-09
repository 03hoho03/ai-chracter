import { describe, expect, it } from "vitest";

import { toUniqueWebnovels } from "./uniqueWebnovels";

describe("toUniqueWebnovels", () => {
  it("keeps a novel repeated across pages only where it first appeared", () => {
    const pages = [{ items: [{ id: "a" }, { id: "b" }] }, { items: [{ id: "b" }, { id: "c" }] }];
    expect(toUniqueWebnovels(pages).map((item) => item.id)).toEqual(["a", "b", "c"]);
  });

  it("returns an empty list for no pages", () => {
    expect(toUniqueWebnovels([])).toEqual([]);
  });
});
