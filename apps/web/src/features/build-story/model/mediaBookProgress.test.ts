import { describe, expect, it } from "vitest";

import { toUsedAssetLabels } from "./mediaBookProgress";
import type { MediaBookCellValues, MediaBookValues } from "./schema";

const DOHEE = "00000000-0000-4000-8000-000000000001";
const YUNA = "00000000-0000-4000-8000-000000000002";
const READING = "00000000-0000-4000-8000-000000000011";
const HEART = "00000000-0000-4000-8000-000000000012";
const SHARED_ASSET = "00000000-0000-4000-8000-000000000031";
const OTHER_ASSET = "00000000-0000-4000-8000-000000000032";

function cell(id: string, personId: string, sceneId: string, imageAssetId: string): MediaBookCellValues {
  return { id, personId, sceneId, imageAssetId, situationDescription: "", unlockHint: "", excludeFromChat: false };
}

const BOOK: MediaBookValues = {
  people: [
    { id: DOHEE, name: "도희" },
    { id: YUNA, name: "유나" },
  ],
  scenes: [
    { id: READING, name: "리딩" },
    { id: HEART, name: "진심" },
  ],
  cells: [
    // 표 순서(장면 → 인물)와 일부러 다르게 넣는다.
    cell("00000000-0000-4000-8000-000000000021", DOHEE, HEART, SHARED_ASSET),
    cell("00000000-0000-4000-8000-000000000022", YUNA, READING, SHARED_ASSET),
    cell("00000000-0000-4000-8000-000000000023", DOHEE, READING, OTHER_ASSET),
  ],
};

describe("toUsedAssetLabels", () => {
  it("names every other cell that uses the same image, in table order", () => {
    const labels = toUsedAssetLabels(BOOK, { personId: DOHEE, sceneId: READING });

    expect(labels.get(SHARED_ASSET)).toBe("유나 · 리딩, 도희 · 진심 칸에 씀");
  });

  it("leaves out the cell being filled so its own image is not reported as used elsewhere", () => {
    const labels = toUsedAssetLabels(BOOK, { personId: DOHEE, sceneId: READING });

    expect(labels.has(OTHER_ASSET)).toBe(false);
    expect(toUsedAssetLabels(BOOK, { personId: YUNA, sceneId: READING }).get(SHARED_ASSET)).toBe("도희 · 진심 칸에 씀");
  });

  it("skips a cell whose person or scene no longer exists", () => {
    const book = { ...BOOK, people: BOOK.people.filter((person) => person.id !== YUNA) };

    expect(toUsedAssetLabels(book, { personId: DOHEE, sceneId: READING }).get(SHARED_ASSET)).toBe("도희 · 진심 칸에 씀");
  });

  it("is empty for an empty media book", () => {
    expect(toUsedAssetLabels({ people: [], scenes: [], cells: [] }, { personId: DOHEE, sceneId: READING }).size).toBe(0);
  });
});
