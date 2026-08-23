import { describe, expect, it } from "vitest";

import { createEmptyDraft } from "./emptyDraft";

describe("createEmptyDraft", () => {
  it("mirrors the empty character draft that POST /contents creates", () => {
    expect(createEmptyDraft("character")).toEqual({
      type: "character",
      name: "",
      oneLiner: "",
      thumbnailAssetId: null,
      intro: "",
      exampleDialogues: [],
      characterPrompt: "",
      playguide: null,
      situationalImages: [],
      description: "",
      genreId: null,
      target: null,
      hashtags: [],
      visibility: "private",
    });
  });

  it("mirrors the empty story draft that POST /contents creates", () => {
    expect(createEmptyDraft("story")).toEqual({
      type: "story",
      name: "",
      oneLiner: "",
      thumbnailAssetId: null,
      promptTemplate: "basic",
      settingText: null,
      developmentExample: null,
      customPrompt: null,
      startingSetups: [],
      keywordNotes: [],
      shortcuts: [],
      description: "",
      genreId: null,
      target: null,
      hashtags: [],
      visibility: "private",
    });
  });

  it("hands out a fresh object per call so one builder's edits never leak into the next", () => {
    expect(createEmptyDraft("character")).not.toBe(createEmptyDraft("character"));
  });
});
