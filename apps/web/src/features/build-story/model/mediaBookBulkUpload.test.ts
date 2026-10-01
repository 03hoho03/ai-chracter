import { describe, expect, it } from "vitest";

import {
  applyBulkUploadEntry,
  finalizeBulkUploadPlan,
  knownAxisNamesOf,
  parseMediaFileName,
  planBulkUpload,
} from "./mediaBookBulkUpload";
import type { CellImageResult } from "./mediaBookEdit";
import { MAX_MEDIA_BOOK_CELLS, mediaBookSchema, type MediaBookCellValues, type MediaBookValues } from "./schema";

const PERSON = "00000000-0000-4000-8000-000000000001";
const SCENE = "00000000-0000-4000-8000-000000000011";
const CELL = "00000000-0000-4000-8000-000000000021";
const OLD_ASSET = "00000000-0000-4000-8000-000000000031";
const NEW_ASSET = "00000000-0000-4000-8000-000000000032";

const FILLED_CELL: MediaBookCellValues = {
  id: CELL,
  personId: PERSON,
  sceneId: SCENE,
  imageAssetId: OLD_ASSET,
  imageUrl: "https://example.test/old",
  imageWidth: 300,
  imageHeight: 400,
  situationDescription: "웃는 얼굴",
  unlockHint: "힌트",
  excludeFromChat: true,
};

function idFactory() {
  let next = 100;
  return () => `00000000-0000-4000-8000-${String(next++).padStart(12, "0")}`;
}

const filled: MediaBookValues = {
  people: [{ id: PERSON, name: "에리" }],
  scenes: [{ id: SCENE, name: "기쁨" }],
  cells: [FILLED_CELL],
};

describe("parseMediaFileName", () => {
  it("splits at the first underscore so later underscores stay in the scene", () => {
    expect(parseMediaFileName("에리_기쁨_2.webp")).toEqual({ ok: true, person: "에리", scene: "기쁨_2" });
  });

  it("rejects a name without an underscore", () => {
    expect(parseMediaFileName("에리기쁨.png")).toMatchObject({ ok: false });
  });

  it("strips every trailing image extension but keeps other dots", () => {
    expect(parseMediaFileName("에리_기쁨.png.webp")).toEqual({ ok: true, person: "에리", scene: "기쁨" });
    expect(parseMediaFileName("에리_v1.2.JPG")).toEqual({ ok: true, person: "에리", scene: "v1.2" });
  });

  it("composes NFD file names (macOS Finder) into the same NFC names", () => {
    const parsed = parseMediaFileName("에리_기쁨.png".normalize("NFD"));

    expect(parsed).toEqual({ ok: true, person: "에리", scene: "기쁨" });
  });

  it("rejects names that break the axis name rules", () => {
    expect(parseMediaFileName("_기쁨.png")).toMatchObject({ ok: false });
    expect(parseMediaFileName("에리_가:나.png")).toMatchObject({ ok: false });
    expect(parseMediaFileName(`에리_${"가".repeat(21)}.png`)).toMatchObject({ ok: false });
  });
});

describe("planBulkUpload", () => {
  it("marks files for filled cells as overwrites and keeps only the first file per cell", () => {
    const plan = planBulkUpload(["에리_기쁨.png", "에리_슬픔.png", "에리_슬픔.webp", "규칙위반.png"], filled);

    expect(plan.entries).toEqual([
      { fileIndex: 0, fileName: "에리_기쁨.png", person: "에리", scene: "기쁨", isOverwrite: true },
      { fileIndex: 1, fileName: "에리_슬픔.png", person: "에리", scene: "슬픔", isOverwrite: false },
    ]);
    expect(plan.excluded.map((item) => item.fileName)).toEqual(["에리_슬픔.webp", "규칙위반.png"]);
  });
});

describe("finalizeBulkUploadPlan", () => {
  it("drops overwrites when the user chose to skip filled cells", () => {
    const plan = planBulkUpload(["에리_기쁨.png", "에리_슬픔.png"], filled);

    const final = finalizeBulkUploadPlan(plan, filled, "skip");

    expect(final.entries.map((entry) => entry.fileName)).toEqual(["에리_슬픔.png"]);
    expect(final.excluded.map((item) => item.fileName)).toEqual(["에리_기쁨.png"]);
  });

  it("excludes new cells past the cap but still lets overwrites through", () => {
    const createId = idFactory();
    const cells = Array.from({ length: MAX_MEDIA_BOOK_CELLS - 2 }, (_, index) => ({
      ...FILLED_CELL,
      id: createId(),
      sceneId: `00000000-0000-4000-8000-${String(500 + index).padStart(12, "0")}`,
    }));
    const nearlyFull: MediaBookValues = { ...filled, cells: [...filled.cells, ...cells] };
    const plan = planBulkUpload(["에리_새1.png", "에리_새2.png", "에리_기쁨.png"], nearlyFull);

    const final = finalizeBulkUploadPlan(plan, nearlyFull, "overwrite");

    expect(final.entries.map((entry) => entry.fileName)).toEqual(["에리_새1.png", "에리_기쁨.png"]);
    expect(final.excluded.map((item) => item.fileName)).toEqual(["에리_새2.png"]);
  });
});

/** 거절이면 테스트를 실패시키고, 받아들였으면 새 미디어 북을 돌려준다. */
function accepted(result: CellImageResult): MediaBookValues {
  if (!result.ok) throw new Error(`refused: ${result.reason}`);
  return result.mediaBook;
}

describe("applyBulkUploadEntry", () => {
  it("keeps the cell id and its text when overwriting, swapping only the image", () => {
    const next = accepted(
      applyBulkUploadEntry(
        filled,
        { person: "에리", scene: "기쁨" },
        { assetId: NEW_ASSET, imageUrl: "blob:new" },
        idFactory(),
        knownAxisNamesOf(filled),
      ),
    );

    expect(next.cells).toEqual([
      {
        ...FILLED_CELL,
        imageAssetId: NEW_ASSET,
        imageUrl: "blob:new",
        imageWidth: undefined,
        imageHeight: undefined,
      },
    ]);
    expect(next.people).toEqual(filled.people);
  });

  it("creates missing axes and a new cell, producing a value the form schema accepts", () => {
    const next = accepted(
      applyBulkUploadEntry(filled, { person: "하나", scene: "기쁨" }, { assetId: NEW_ASSET }, idFactory(), knownAxisNamesOf(filled)),
    );

    expect(next.people.map((person) => person.name)).toEqual(["에리", "하나"]);
    expect(next.scenes).toEqual(filled.scenes);
    expect(next.cells).toHaveLength(2);
    expect(mediaBookSchema.safeParse(next).success).toBe(true);
  });

  it("does not bring back a person the author deleted while the batch was uploading", () => {
    // 업로드를 시작할 때는 에리가 있었다.
    const known = knownAxisNamesOf(filled);
    const deletedDuringUpload: MediaBookValues = { ...filled, people: [], cells: [] };

    const result = applyBulkUploadEntry(
      deletedDuringUpload,
      { person: "에리", scene: "슬픔" },
      { assetId: NEW_ASSET },
      idFactory(),
      known,
    );

    expect(result).toEqual({ ok: false, reason: "missing-axis" });
  });

  it("does not bring back an axis this batch created and the author then deleted", () => {
    const known = knownAxisNamesOf(filled);
    known.person.set("하나", "00000000-0000-4000-8000-000000000077");

    const result = applyBulkUploadEntry(filled, { person: "하나", scene: "기쁨" }, { assetId: NEW_ASSET }, idFactory(), known);

    expect(result).toEqual({ ok: false, reason: "missing-axis" });
  });

  it("says the axis was renamed, not deleted, when its id survives under another name", () => {
    const known = knownAxisNamesOf(filled);
    const renamedDuringUpload: MediaBookValues = { ...filled, people: [{ id: PERSON, name: "에린" }] };

    const result = applyBulkUploadEntry(
      renamedDuringUpload,
      { person: "에리", scene: "슬픔" },
      { assetId: NEW_ASSET },
      idFactory(),
      known,
    );

    expect(result).toEqual({ ok: false, reason: "renamed-axis" });
  });
});
