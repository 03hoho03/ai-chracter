import { describe, expect, it } from "vitest";

import type { NovelChapterSummary, NovelSnapshotChapter } from "@/entities/novel";

import {
  toSkippedChaptersNotice,
  toSnapshotChapterRows,
  toSnapshotCharacterRows,
  toSnapshotFieldRows,
} from "./snapshotCompare";

function chapter(id: string, ordinal: number, extra: Partial<NovelChapterSummary> = {}): NovelChapterSummary {
  return {
    id,
    ordinal,
    assistantMessageCount: 1,
    currentRevisionId: `r-${id}`,
    currentRevisionNo: 1,
    currentRevisionSource: "generate",
    updatedAt: "2026-10-08T00:00:00Z",
    createdAt: "2026-10-08T00:00:00Z",
    batchId: "b",
    episodeIndex: 0,
    title: `제목 ${id}`,
    titleEdited: false,
    summary: null,
    authorNote: "",
    charCount: 1,
    finishedReading: false,
    readingPosition: null,
    ...extra,
  };
}

function item(chapterId: string, extra: Partial<NovelSnapshotChapter> = {}): NovelSnapshotChapter {
  return {
    chapterId,
    deleted: false,
    revisionId: `r-${chapterId}`,
    title: `제목 ${chapterId}`,
    summary: null,
    authorNote: "",
    ...extra,
  };
}

describe("toSnapshotChapterRows", () => {
  it("marks a chapter changed when its revision, title or author's note differs, and unchanged otherwise", () => {
    const rows = toSnapshotChapterRows(
      { chapters: [item("a"), item("b", { revisionId: "old" }), item("c", { title: "옛 제목" }), item("d", { authorNote: "옛 말" })] },
      [chapter("a", 1), chapter("b", 2), chapter("c", 3), chapter("d", 4)],
    );
    expect(rows.map((row) => (row.kind === "kept" ? [row.chapterId, row.isChanged] : row.kind))).toEqual([
      ["a", false],
      ["b", true],
      ["c", true],
      ["d", true],
    ]);
  });

  it("treats a missing author's note in an old snapshot as empty", () => {
    const [row] = toSnapshotChapterRows({ chapters: [item("a", { authorNote: null })] }, [chapter("a", 1)]);
    expect(row).toMatchObject({ kind: "kept", isChanged: false });
  });

  it("lists chapters deleted after the snapshot (flagged or gone from the detail) as deleted", () => {
    const rows = toSnapshotChapterRows(
      { chapters: [item("a"), item("b", { deleted: true, revisionId: null }), item("c")] },
      [chapter("a", 1)],
    );
    expect(rows.map((row) => [row.kind, row.chapterId])).toEqual([
      ["kept", "a"],
      ["deleted", "b"],
      ["deleted", "c"],
    ]);
  });

  it("appends chapters made after the snapshot in episode order", () => {
    const rows = toSnapshotChapterRows({ chapters: [item("a")] }, [chapter("z", 3), chapter("a", 1), chapter("y", 2)]);
    expect(rows.map((row) => [row.kind, row.chapterId])).toEqual([
      ["kept", "a"],
      ["added", "y"],
      ["added", "z"],
    ]);
  });
});

describe("toSnapshotFieldRows", () => {
  it("compares title (null as empty), synopsis and notes", () => {
    const rows = toSnapshotFieldRows(
      { title: null, synopsis: "소개", settingNotes: "옛 노트" },
      { title: null, synopsis: "소개", settingNotes: "새 노트" },
    );
    expect(rows.map((row) => [row.label, row.isChanged])).toEqual([
      ["소설 제목", false],
      ["소개", false],
      ["설정 노트", true],
    ]);
  });
});

describe("toSnapshotCharacterRows", () => {
  const snapshot = {
    characters: [
      { id: "c1", name: "도희", aliases: [], memo: "야간 점원" },
      { id: "c2", name: "도희 씨", aliases: [], memo: "같은 사람" },
      { id: "c3", name: "세빈", aliases: [], memo: "" },
    ],
  };

  it("matches the same card, or the surviving card that took the merged name as an alias", () => {
    const rows = toSnapshotCharacterRows(snapshot, [
      { id: "c1", name: "도희", aliases: ["도희 씨"], memo: "야간 점원\n[도희 씨] 같은 사람" },
    ]);
    expect(rows.map((row) => [row.snapshotCharacterId, row.currentName, row.isMerged, row.isChanged])).toEqual([
      ["c1", "도희", false, true],
      ["c2", "도희", true, true],
      ["c3", undefined, false, true],
    ]);
  });

  it("is unchanged when the same card keeps its name and memo", () => {
    const [row] = toSnapshotCharacterRows(
      { characters: [{ id: "c1", name: "도희", aliases: [], memo: "야간 점원" }] },
      [{ id: "c1", name: "도희", aliases: ["희"], memo: "야간 점원" }],
    );
    expect(row?.isChanged).toBe(false);
  });
});

describe("toSkippedChaptersNotice", () => {
  it("says nothing when nothing was skipped", () => {
    expect(toSkippedChaptersNotice([], [])).toBeUndefined();
  });

  it("names chapters still in the table of contents and counts the ones gone from it", () => {
    expect(toSkippedChaptersNotice(["b", "gone1", "a", "gone2"], [chapter("a", 1), chapter("b", 4)])).toBe(
      "1화·4화는 그때 글이 남아 있지 않아 되돌리지 못했어요. 지워진 화 2개는 되돌리지 못했어요.",
    );
    expect(toSkippedChaptersNotice(["gone"], [])).toBe("지워진 화 1개는 되돌리지 못했어요.");
  });
});
