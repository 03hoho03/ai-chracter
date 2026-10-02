import { describe, expect, it } from "vitest";

import {
  findNextIncompleteCell,
  formatMediaBookProgress,
  summarizeMediaBookProgress,
  toUsedAssetLabels,
} from "./mediaBookProgress";
import { MAX_MEDIA_BOOK_CELLS, type MediaBookCellValues, type MediaBookValues } from "./schema";

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

// 2인물 × 2장면 표. 칸은 줄(장면) → 칸(인물) 순서로 도희×리딩, 유나×리딩, 도희×진심, 유나×진심.
function bookWith(cells: MediaBookCellValues[]): MediaBookValues {
  return { people: BOOK.people, scenes: BOOK.scenes, cells };
}

function described(id: string, personId: string, sceneId: string, situationDescription = "웃는 얼굴"): MediaBookCellValues {
  return { ...cell(id, personId, sceneId, OTHER_ASSET), situationDescription };
}

const CELL_A = "00000000-0000-4000-8000-000000000041";
const CELL_B = "00000000-0000-4000-8000-000000000042";
const CELL_C = "00000000-0000-4000-8000-000000000043";

describe("findNextIncompleteCell", () => {
  it("walks scene rows first, then people within a row", () => {
    // 도희×리딩만 채웠다 — 다음은 같은 줄의 유나×리딩이지 아래 줄의 도희×진심이 아니다.
    const book = bookWith([described(CELL_A, DOHEE, READING)]);

    expect(findNextIncompleteCell(book, { personId: DOHEE, sceneId: READING })).toEqual({ personId: YUNA, sceneId: READING });
  });

  it("wraps from the last cell back to the first", () => {
    const book = bookWith([described(CELL_A, YUNA, READING), described(CELL_B, DOHEE, HEART)]);

    expect(findNextIncompleteCell(book, { personId: YUNA, sceneId: HEART })).toEqual({ personId: DOHEE, sceneId: READING });
  });

  it("never returns the current cell even when it is the only incomplete one", () => {
    const book = bookWith([described(CELL_A, YUNA, READING), described(CELL_B, DOHEE, HEART), described(CELL_C, YUNA, HEART)]);

    expect(findNextIncompleteCell(book, { personId: DOHEE, sceneId: READING })).toBeUndefined();
  });

  it("counts a filled cell whose situation description is only spaces as incomplete", () => {
    const book = bookWith([
      described(CELL_A, DOHEE, READING),
      described(CELL_B, YUNA, READING, "   "),
      described(CELL_C, DOHEE, HEART),
      described("00000000-0000-4000-8000-000000000044", YUNA, HEART),
    ]);

    expect(findNextIncompleteCell(book, { personId: DOHEE, sceneId: READING })).toEqual({ personId: YUNA, sceneId: READING });
  });

  it("ignores an empty unlock hint", () => {
    const book = bookWith([
      described(CELL_A, DOHEE, READING),
      described(CELL_B, YUNA, READING),
      described(CELL_C, DOHEE, HEART),
      described("00000000-0000-4000-8000-000000000044", YUNA, HEART),
    ]);

    expect(findNextIncompleteCell(book, { personId: DOHEE, sceneId: READING })).toBeUndefined();
  });

  it("skips empty cells once the image cap is reached, leaving only filled cells without a description", () => {
    // 도희×리딩은 비었고 도희×진심은 설명이 없다. 유나×진심(지금 칸)에서 돌아 처음으로 가면 빈 도희×리딩이 먼저다.
    const cells = [described(CELL_A, YUNA, READING), described(CELL_B, DOHEE, HEART, "")];
    const book = bookWith(cells);
    const capped = { ...book, cells: [...cells, ...fillerCells(MAX_MEDIA_BOOK_CELLS - cells.length)] };

    expect(findNextIncompleteCell(book, { personId: YUNA, sceneId: HEART })).toEqual({ personId: DOHEE, sceneId: READING });
    expect(findNextIncompleteCell(capped, { personId: YUNA, sceneId: HEART })).toEqual({ personId: DOHEE, sceneId: HEART });
  });

  it("has nothing to offer when the table has no cells", () => {
    expect(findNextIncompleteCell({ people: [], scenes: [], cells: [] }, { personId: DOHEE, sceneId: READING })).toBeUndefined();
  });
});

describe("summarizeMediaBookProgress", () => {
  it("counts table cells, filled cells and filled cells without a description", () => {
    const book = bookWith([described(CELL_A, DOHEE, READING), described(CELL_B, YUNA, HEART, " ")]);

    expect(summarizeMediaBookProgress(book)).toEqual({
      totalCells: 4,
      filledCells: 2,
      missingDescriptionCells: 1,
      isOverCellLimit: false,
    });
  });

  it("is all zero when one axis is empty", () => {
    expect(summarizeMediaBookProgress({ people: BOOK.people, scenes: [], cells: [] })).toEqual({
      totalCells: 0,
      filledCells: 0,
      missingDescriptionCells: 0,
      isOverCellLimit: false,
    });
  });

  it("flags a table with more cells than the image cap, but not one exactly at the cap", () => {
    const people = Array.from({ length: 10 }, (_, index) => ({ id: `p${index}`, name: `인물${index}` }));
    const fiveScenes = Array.from({ length: 5 }, (_, index) => ({ id: `s${index}`, name: `장면${index}` }));
    const sixScenes = [...fiveScenes, { id: "s5", name: "장면5" }];

    expect(summarizeMediaBookProgress({ people, scenes: fiveScenes, cells: [] }).isOverCellLimit).toBe(false);
    expect(summarizeMediaBookProgress({ people, scenes: sixScenes, cells: [] }).isOverCellLimit).toBe(true);
  });
});

describe("formatMediaBookProgress", () => {
  const base = { totalCells: 21, filledCells: 3, missingDescriptionCells: 0, isOverCellLimit: false };

  it("says how many of the cells are filled", () => {
    expect(formatMediaBookProgress(base)).toBe("21칸 중 3칸 채움");
  });

  it("adds the count of filled cells without a description only when there are some", () => {
    expect(formatMediaBookProgress({ ...base, missingDescriptionCells: 2 })).toBe("21칸 중 3칸 채움 · 상황 설명 없는 칸 2");
  });

  it("adds the image cap only when the table is larger than it", () => {
    expect(formatMediaBookProgress({ ...base, totalCells: 60, isOverCellLimit: true })).toBe(
      `60칸 중 3칸 채움 · 이미지는 ${MAX_MEDIA_BOOK_CELLS}칸까지 넣을 수 있어요`,
    );
  });

  it("says everything is filled only when every cell has an image and a description", () => {
    expect(formatMediaBookProgress({ ...base, filledCells: 21 })).toBe("21칸 모두 채움");
    expect(formatMediaBookProgress({ ...base, filledCells: 21, missingDescriptionCells: 1 })).toBe(
      "21칸 중 21칸 채움 · 상황 설명 없는 칸 1",
    );
  });
});

/** 표 밖(없는 인물·장면)을 가리키는 칸 — 상한 셈에만 쓰인다. */
function fillerCells(count: number): MediaBookCellValues[] {
  return Array.from({ length: count }, (_, index) => ({
    ...cell(`filler-${index}`, `gone-person-${index}`, READING, OTHER_ASSET),
    situationDescription: "x",
  }));
}
