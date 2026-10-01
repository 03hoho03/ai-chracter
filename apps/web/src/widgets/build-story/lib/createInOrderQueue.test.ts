import { describe, expect, it } from "vitest";

import {
  applyBulkUploadEntry,
  knownAxisNamesOf,
  planBulkUpload,
  type MediaBookValues,
} from "@/features/build-story";

import { createInOrderQueue } from "./createInOrderQueue";

describe("createInOrderQueue", () => {
  it("applies results in index order however they arrive", () => {
    const applied: number[] = [];
    const complete = createInOrderQueue<string>((index) => applied.push(index));

    complete(1, "b");
    complete(2, "c");
    expect(applied).toEqual([]);
    complete(0, "a");
    expect(applied).toEqual([0, 1, 2]);
  });

  it("creates new scenes in file order when uploads finish out of order", () => {
    const empty: MediaBookValues = { people: [], scenes: [], cells: [] };
    const plan = planBulkUpload(["대량_s01.png", "대량_s02.png", "대량_s03.png"], empty);
    let mediaBook = empty;
    const known = knownAxisNamesOf(empty);
    let id = 0;
    const complete = createInOrderQueue<string>((index, assetId) => {
      const entry = plan.entries[index];
      if (!entry) return;
      const result = applyBulkUploadEntry(mediaBook, entry, { assetId }, () => `id-${id++}`, known);
      if (result.ok) mediaBook = result.mediaBook;
    });

    // 업로드가 끝난 순서: 2, 3, 1
    complete(1, "asset-2");
    complete(2, "asset-3");
    complete(0, "asset-1");

    expect(mediaBook.scenes.map((scene) => scene.name)).toEqual(["s01", "s02", "s03"]);
  });
});
