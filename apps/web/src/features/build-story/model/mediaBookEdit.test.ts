import { describe, expect, it } from "vitest";

import {
  addAxisItem,
  countAxisItemCells,
  mediaBookNameError,
  removeAxisItem,
  renameAxisItem,
  setCellImage,
  type CellImageResult,
} from "./mediaBookEdit";
import {
  MAX_MEDIA_BOOK_CELLS,
  MEDIA_BOOK_DUPLICATE_NAME_MESSAGE,
  mediaBookSchema,
  type MediaBookCellValues,
  type MediaBookValues,
} from "./schema";

const PERSON_A = "00000000-0000-4000-8000-000000000001";
const PERSON_B = "00000000-0000-4000-8000-000000000002";
const SCENE = "00000000-0000-4000-8000-000000000011";
const NEW_ID = "00000000-0000-4000-8000-000000000099";

const CELL: MediaBookCellValues = {
  id: "00000000-0000-4000-8000-000000000021",
  personId: PERSON_A,
  sceneId: SCENE,
  imageAssetId: "00000000-0000-4000-8000-000000000031",
  situationDescription: "",
  unlockHint: "",
  excludeFromChat: false,
};

const BASE_BOOK: MediaBookValues = {
  people: [
    { id: PERSON_A, name: "에리" },
    { id: PERSON_B, name: "하나" },
  ],
  scenes: [{ id: SCENE, name: "기쁨" }],
  cells: [CELL],
};

describe("mediaBookNameError", () => {
  it("rejects a name equal to a sibling after trimming and NFC, but not the item's own name", () => {
    expect(mediaBookNameError(` ${"에리".normalize("NFD")}`, BASE_BOOK.people)).toBe(MEDIA_BOOK_DUPLICATE_NAME_MESSAGE);
    expect(mediaBookNameError("에리", BASE_BOOK.people, PERSON_A)).toBeUndefined();
  });

  it("says the same duplicate-name sentence as the form schema", () => {
    const duplicated = { ...BASE_BOOK, people: [...BASE_BOOK.people, { id: NEW_ID, name: "에리" }] };
    const issues = mediaBookSchema.safeParse(duplicated).error?.issues ?? [];

    expect(issues.map((issue) => issue.message)).toContain(mediaBookNameError("에리", BASE_BOOK.people));
  });

  it("reuses the form schema messages for blank and forbidden names", () => {
    expect(mediaBookNameError("  ", [])).toBe("이름을 입력해주세요");
    expect(mediaBookNameError("a/b", [])).toBe("이름에는 / { } : 를 쓸 수 없습니다");
  });
});

describe("axis edits", () => {
  it("stores names trimmed and NFC-composed so the saved value matches what the server keeps", () => {
    const added = addAxisItem(BASE_BOOK, "scene", ` ${"슬픔".normalize("NFD")} `, NEW_ID);

    expect(added.scenes.at(-1)).toEqual({ id: NEW_ID, name: "슬픔" });
    expect(renameAxisItem(BASE_BOOK, "person", PERSON_B, " 두리 ").people[1]).toEqual({ id: PERSON_B, name: "두리" });
  });

  it("removes the axis item together with the cells on its line", () => {
    expect(countAxisItemCells(BASE_BOOK, "person", PERSON_A)).toBe(1);

    const removed = removeAxisItem(BASE_BOOK, "person", PERSON_A);

    expect(removed.people.map((person) => person.id)).toEqual([PERSON_B]);
    expect(removed.cells).toEqual([]);
    expect(mediaBookSchema.safeParse(removed).success).toBe(true);
  });
});

/** 거절이면 테스트를 실패시키고, 받아들였으면 새 미디어 북을 돌려준다. */
function accepted(result: CellImageResult): MediaBookValues {
  if (!result.ok) throw new Error(`refused: ${result.reason}`);
  return result.mediaBook;
}

describe("setCellImage", () => {
  it("keeps the cell id when the image of a filled cell changes", () => {
    const next = accepted(setCellImage(BASE_BOOK, PERSON_A, SCENE, { assetId: NEW_ID }, () => "unused"));

    expect(next.cells).toHaveLength(1);
    expect(next.cells[0]?.id).toBe(CELL.id);
    expect(next.cells[0]?.imageAssetId).toBe(NEW_ID);
  });

  it("creates a cell with a fresh id for an empty position and refuses past the cap", () => {
    const next = accepted(setCellImage(BASE_BOOK, PERSON_B, SCENE, { assetId: NEW_ID }, () => NEW_ID));

    expect(next.cells.at(-1)).toMatchObject({ id: NEW_ID, personId: PERSON_B, sceneId: SCENE, excludeFromChat: false });

    const full: MediaBookValues = {
      ...BASE_BOOK,
      cells: Array.from({ length: MAX_MEDIA_BOOK_CELLS }, (_, index) => ({ ...CELL, id: String(index) })),
    };
    expect(setCellImage(full, PERSON_B, SCENE, { assetId: NEW_ID }, () => NEW_ID)).toEqual({ ok: false, reason: "cap" });
  });

  it("refuses a cell whose person or scene was removed while the upload was running", () => {
    const withoutPerson = removeAxisItem(BASE_BOOK, "person", PERSON_B);

    expect(setCellImage(withoutPerson, PERSON_B, SCENE, { assetId: NEW_ID }, () => NEW_ID)).toEqual({
      ok: false,
      reason: "missing-axis",
    });
    // 채운 칸이라도 축이 사라졌으면 쓰지 않는다.
    const withoutScene = { ...BASE_BOOK, scenes: [] };
    expect(setCellImage(withoutScene, PERSON_A, SCENE, { assetId: NEW_ID }, () => NEW_ID)).toEqual({
      ok: false,
      reason: "missing-axis",
    });
  });
});
