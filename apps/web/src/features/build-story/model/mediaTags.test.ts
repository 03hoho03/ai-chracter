import { describe, expect, it } from "vitest";

import { toMediaNameTag } from "@/entities/media-book";

import { findUnknownMediaTags, insertMediaTag, renameMediaTagsInFields } from "./mediaTags";
import type { MediaBookValues, StartingSetupValues, StoryBuilderFormValues } from "./schema";

const PERSON_RIA = "00000000-0000-4000-8000-000000000001";
const PERSON_MARIA = "00000000-0000-4000-8000-000000000002";
const SCENE_JOY = "00000000-0000-4000-8000-000000000011";
const SCENE_SAD = "00000000-0000-4000-8000-000000000012";

const MEDIA_BOOK: MediaBookValues = {
  people: [
    { id: PERSON_RIA, name: "리아" },
    { id: PERSON_MARIA, name: "마리아" },
  ],
  scenes: [
    { id: SCENE_JOY, name: "기쁨" },
    { id: SCENE_SAD, name: "슬픔" },
  ],
  cells: [
    {
      id: "00000000-0000-4000-8000-000000000021",
      personId: PERSON_RIA,
      sceneId: SCENE_JOY,
      imageAssetId: "00000000-0000-4000-8000-000000000031",
      situationDescription: "",
      unlockHint: "",
      excludeFromChat: false,
    },
  ],
};

function setup(overrides: Partial<StartingSetupValues>): StartingSetupValues {
  return {
    id: "setup",
    name: "설정",
    prologue: "",
    openingSituation: "",
    playGuide: "",
    suggestedReplies: [],
    stats: [],
    endings: [],
    situationNotes: [],
    ...overrides,
  };
}

function ending(epilogue: string): StartingSetupValues["endings"][number] {
  return { id: "ending", name: "엔딩", turnGate: 10, judgePrompt: "판단", statRules: [], epilogue, priorityStatId: null };
}

describe("renameMediaTagsInFields", () => {
  it("rewrites every starting setup and every ending plus the registration description, reporting only changed fields", () => {
    const values: Pick<StoryBuilderFormValues, "startingSetups" | "registration"> = {
      startingSetups: [
        setup({ prologue: "{{img::리아/기쁨}}", openingSituation: "태그 없음", endings: [ending("{{img::리아/슬픔}}")] }),
        setup({
          openingSituation: "{{img::리아/기쁨}}",
          playGuide: "{{img::리아/기쁨}}",
          endings: [ending("없음"), ending("끝 {{img::리아/기쁨}}")],
        }),
      ],
      registration: {
        description: "{{img::마리아/기쁨}} {{img::리아/기쁨}}",
        genre: null,
        target: null,
        hashtags: [],
        visibility: "private",
        novelPermission: "private",
      },
    };

    expect(renameMediaTagsInFields(values, "person", "리아", "레아")).toEqual([
      { path: "startingSetups.0.prologue", value: "{{img::레아/기쁨}}" },
      { path: "startingSetups.0.endings.0.epilogue", value: "{{img::레아/슬픔}}" },
      { path: "startingSetups.1.openingSituation", value: "{{img::레아/기쁨}}" },
      { path: "startingSetups.1.endings.1.epilogue", value: "끝 {{img::레아/기쁨}}" },
      { path: "registration.description", value: "{{img::마리아/기쁨}} {{img::레아/기쁨}}" },
    ]);
  });
});

describe("findUnknownMediaTags", () => {
  it("reports tags that point at no filled cell, once each and in order", () => {
    const text = "{{img::리아/슬픔}} {{img::리아/기쁨}} {{img::없음/기쁨}} {{img::리아/슬픔}}";

    expect(findUnknownMediaTags(text, MEDIA_BOOK)).toEqual(["{{img::리아/슬픔}}", "{{img::없음/기쁨}}"]);
  });

  it("treats a tag with NFD or padded names as the same filled cell", () => {
    expect(findUnknownMediaTags(`{{img:: ${"리아".normalize("NFD")}/기쁨 }}`, MEDIA_BOOK)).toEqual([]);
  });

  it("ignores id-form tags and non-tags", () => {
    expect(findUnknownMediaTags("{{img::00000000-0000-4000-8000-000000000099}} {{user}}", MEDIA_BOOK)).toEqual([]);
  });
});

describe("insertMediaTag", () => {
  it("inserts at the caret and puts the caret after the tag", () => {
    const tag = toMediaNameTag("리아", "기쁨");

    expect(insertMediaTag({ text: "앞뒤", selectionStart: 1, selectionEnd: 1 }, tag)).toEqual({
      text: `앞${tag}뒤`,
      selectionStart: 1 + tag.length,
      selectionEnd: 1 + tag.length,
    });
  });

  it("replaces a backwards selection", () => {
    expect(insertMediaTag({ text: "가나다라", selectionStart: 3, selectionEnd: 1 }, "T")).toEqual({
      text: "가T라",
      selectionStart: 2,
      selectionEnd: 2,
    });
  });
});
