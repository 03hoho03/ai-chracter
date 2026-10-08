import { describe, expect, it } from "vitest";

import type { NovelChapterSummary, NovelDetailResponse } from "@/entities/novel";

import { toBoardModel, toEpisodeReadState } from "./toBoardModel";

function chapter(id: string, batchId: string, ordinal: number, extra: Partial<NovelChapterSummary> = {}): NovelChapterSummary {
  return {
    id,
    ordinal,
    assistantMessageCount: 1,
    currentRevisionId: `r-${id}`,
    currentRevisionNo: 1,
    currentRevisionSource: "generate",
    updatedAt: "2026-10-08T00:00:00Z",
    createdAt: "2026-10-08T00:00:00Z",
    batchId,
    episodeIndex: 0,
    title: null,
    titleEdited: false,
    summary: null,
    authorNote: "",
    charCount: 100,
    finishedReading: false,
    readingPosition: null,
    ...extra,
  };
}

type BoardSource = Pick<NovelDetailResponse, "batches" | "chapters" | "settingNotes" | "pendingAiEdits" | "activeJob">;

const novel: BoardSource = {
  batches: [
    { id: "b1", ordinal: 1, chapterIds: ["e1", "e2"], assistantMessageCount: 4, regenerateOptions: [] },
    { id: "b2", ordinal: 2, chapterIds: ["e3"], assistantMessageCount: 2, regenerateOptions: [] },
  ],
  chapters: [chapter("e1", "b1", 1, { title: "첫 손님" }), chapter("e2", "b1", 2), chapter("e3", "b2", 3)],
  settingNotes: "",
  pendingAiEdits: [
    {
      id: "j",
      chapterId: "e2",
      paragraphStart: 0,
      paragraphEnd: 0,
      instruction: "",
      resultText: "",
      createdAt: "2026-10-08T00:00:00Z",
    },
  ],
  activeJob: {
    id: "j2",
    kind: "chapter_regenerate",
    status: "running",
    chapterId: "e3",
    batchId: "b2",
    completedBatches: null,
    plannedBatches: null,
  },
};

describe("toEpisodeReadState", () => {
  const position = { paragraphIndex: 21, paragraphCount: 50, revisionId: "r", finished: false };

  it("finished wins over a saved position (reading the start again keeps it finished)", () => {
    expect(toEpisodeReadState({ finishedReading: true, readingPosition: position })).toEqual({ kind: "finished" });
  });

  it("a saved position becomes the share of the chapter before it, never 100 while unfinished", () => {
    expect(toEpisodeReadState({ finishedReading: false, readingPosition: position })).toEqual({ kind: "reading", percent: 42 });
    expect(
      toEpisodeReadState({ finishedReading: false, readingPosition: { ...position, paragraphIndex: 199, paragraphCount: 200 } }),
    ).toEqual({ kind: "reading", percent: 99 });
  });

  it("no position (or an empty chapter) is unread", () => {
    expect(toEpisodeReadState({ finishedReading: false, readingPosition: null })).toEqual({ kind: "unread" });
    // 화별 읽은 자리를 싣기 전의 API 응답에는 칸이 없다 — 보드를 죽이지 않고 읽지 않은 화로 그린다.
    expect(toEpisodeReadState({ finishedReading: false })).toEqual({ kind: "unread" });
    expect(
      toEpisodeReadState({ finishedReading: false, readingPosition: { ...position, paragraphIndex: 0, paragraphCount: 0 } }),
    ).toEqual({ kind: "unread" });
  });
});

describe("toBoardModel", () => {
  it("names each batch by its episode range and carries card fields per episode", () => {
    const model = toBoardModel(novel, undefined);
    expect(model.batches.map((batch) => batch.rangeLabel)).toEqual(["1~2화", "3화"]);
    expect(model.episodes.map((episode) => [episode.id, episode.title, episode.hasPendingAiEdit, episode.isRegenerating])).toEqual([
      ["e1", "첫 손님", false, false],
      ["e2", null, true, false],
      ["e3", null, false, true],
    ]);
  });

  it("draws the episode column without a character lane while characters are missing", () => {
    expect(toBoardModel(novel, undefined).characters).toEqual([]);
  });

  it("keeps only the character fields the board uses", () => {
    const model = toBoardModel(novel, [
      {
        id: "c1",
        name: "도희",
        aliases: ["도희 씨"],
        memo: "야간 점원",
        chapterIds: ["e1"],
        createdAt: "2026-10-08T00:00:00Z",
        updatedAt: "2026-10-08T00:00:00Z",
      },
    ]);
    expect(model.characters).toEqual([{ id: "c1", name: "도희", aliases: ["도희 씨"], memo: "야간 점원", chapterIds: ["e1"] }]);
  });
});
