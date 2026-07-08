import { describe, expect, it } from "vitest";

import {
  keywordNoteSchema,
  shortcutSchema,
  startingSetupSchema,
  statDefSchema,
  storyBuilderSchema,
  storySettingSchema,
} from "./schema";

describe("storySettingSchema", () => {
  it.each(["basic", "emotional", "simulation"] as const)(
    "requires worldSetting when promptTemplate is %s",
    (promptTemplate) => {
      const result = storySettingSchema.safeParse({ promptTemplate });

      expect(result.success).toBe(false);
      expect(result.success ? [] : result.error.issues.map((issue) => issue.path)).toContainEqual([
        "worldSetting",
      ]);
    },
  );

  it.each(["basic", "emotional", "simulation"] as const)(
    "passes without customPrompt when promptTemplate is %s and worldSetting is set",
    (promptTemplate) => {
      const result = storySettingSchema.safeParse({ promptTemplate, worldSetting: "세계관 설명" });

      expect(result.success).toBe(true);
    },
  );

  it("requires customPrompt when promptTemplate is custom", () => {
    const result = storySettingSchema.safeParse({ promptTemplate: "custom" });

    expect(result.success).toBe(false);
    expect(result.success ? [] : result.error.issues.map((issue) => issue.path)).toContainEqual([
      "customPrompt",
    ]);
  });

  it("passes without worldSetting when promptTemplate is custom and customPrompt is set", () => {
    const result = storySettingSchema.safeParse({
      promptTemplate: "custom",
      customPrompt: "커스텀 프롬프트",
    });

    expect(result.success).toBe(true);
  });

  it("never requires developmentExample regardless of promptTemplate", () => {
    const basic = storySettingSchema.safeParse({
      promptTemplate: "basic",
      worldSetting: "세계관 설명",
    });
    const custom = storySettingSchema.safeParse({
      promptTemplate: "custom",
      customPrompt: "커스텀 프롬프트",
    });

    expect(basic.success).toBe(true);
    expect(custom.success).toBe(true);
  });

  it("defaults promptTemplate to basic when omitted, still requiring worldSetting", () => {
    const missingWorldSetting = storySettingSchema.safeParse({});
    const withWorldSetting = storySettingSchema.safeParse({ worldSetting: "세계관 설명" });

    expect(missingWorldSetting.success).toBe(false);
    expect(withWorldSetting.success).toBe(true);
    expect(withWorldSetting.success && withWorldSetting.data.promptTemplate).toBe("basic");
  });
});

function validStatDef() {
  return {
    id: "stat-1",
    name: "체력",
    icon: "heart",
    color: "rose",
    min: 0,
    max: 100,
    initial: 80,
    unit: "pt",
    description: "생존에 필요한 신체 상태",
  };
}

function validStartingSetup() {
  return {
    id: "setup-1",
    name: "표류 첫날",
    prologue: "배가 좌초되고 눈을 뜨니 낯선 해변이다.",
    stats: [validStatDef()],
  };
}

describe("statDefSchema", () => {
  it("requires name/description and accepts an optional unit", () => {
    const missingName = statDefSchema.safeParse({ ...validStatDef(), name: "" });
    const withoutUnit = statDefSchema.safeParse({ ...validStatDef(), unit: undefined });

    expect(missingName.success).toBe(false);
    expect(withoutUnit.success).toBe(true);
  });

  it("requires min/max/initial to be numbers", () => {
    const result = statDefSchema.safeParse({ ...validStatDef(), min: "0" });

    expect(result.success).toBe(false);
  });
});

describe("startingSetupSchema", () => {
  it("requires name/prologue and defaults suggestedReplies/stats to empty arrays", () => {
    const missingPrologue = startingSetupSchema.safeParse({ ...validStartingSetup(), prologue: "" });
    const minimal = startingSetupSchema.safeParse({
      id: "setup-1",
      name: "표류 첫날",
      prologue: "배가 좌초되고 눈을 뜨니 낯선 해변이다.",
    });

    expect(missingPrologue.success).toBe(false);
    expect(minimal.success).toBe(true);
    expect(minimal.success && minimal.data.suggestedReplies).toEqual([]);
    expect(minimal.success && minimal.data.stats).toEqual([]);
  });

  it("makes openingSituation/playGuide optional", () => {
    const result = startingSetupSchema.safeParse(validStartingSetup());

    expect(result.success).toBe(true);
    expect(result.success && result.data.openingSituation).toBeUndefined();
    expect(result.success && result.data.playGuide).toBeUndefined();
  });
});

describe("keywordNoteSchema", () => {
  function validKeywordNote() {
    return {
      id: "note-1",
      content: "주인공은 밤에만 등장한다.",
      triggerKeywords: ["밤"],
      scope: { kind: "global" as const },
    };
  }

  it("requires content and at least one triggerKeyword", () => {
    const missingContent = keywordNoteSchema.safeParse({ ...validKeywordNote(), content: "" });
    const missingKeywords = keywordNoteSchema.safeParse({ ...validKeywordNote(), triggerKeywords: [] });

    expect(missingContent.success).toBe(false);
    expect(missingKeywords.success).toBe(false);
  });

  it("accepts a global scope with no startingSetupId", () => {
    const result = keywordNoteSchema.safeParse(validKeywordNote());

    expect(result.success).toBe(true);
  });

  it("accepts a startingSetup scope with a startingSetupId", () => {
    const result = keywordNoteSchema.safeParse({
      ...validKeywordNote(),
      scope: { kind: "startingSetup" as const, startingSetupId: "setup-1" },
    });

    expect(result.success).toBe(true);
    expect(result.success && result.data.scope).toEqual({
      kind: "startingSetup",
      startingSetupId: "setup-1",
    });
  });

  it("rejects an unknown scope kind", () => {
    const result = keywordNoteSchema.safeParse({ ...validKeywordNote(), scope: { kind: "unknown" } });

    expect(result.success).toBe(false);
  });
});

describe("shortcutSchema", () => {
  function validShortcut() {
    return { id: "shortcut-1", name: "회상", description: "과거 회상 장면 삽입", prompt: "회상 장면을 묘사해줘" };
  }

  it("requires name/description/prompt", () => {
    expect(shortcutSchema.safeParse({ ...validShortcut(), name: "" }).success).toBe(false);
    expect(shortcutSchema.safeParse({ ...validShortcut(), description: "" }).success).toBe(false);
    expect(shortcutSchema.safeParse({ ...validShortcut(), prompt: "" }).success).toBe(false);
  });

  it("passes with all fields present", () => {
    expect(shortcutSchema.safeParse(validShortcut()).success).toBe(true);
  });
});

describe("storyBuilderSchema startingSetups", () => {
  function validFullForm() {
    return {
      profile: { name: "여름밤의 항해", oneLiner: "바다 위 표류기", image: null },
      storySetting: { promptTemplate: "basic" as const, worldSetting: "근미래 해양 도시" },
      startingSetups: [validStartingSetup()],
      registration: {
        description: "표류한 선원들의 생존기",
        genre: "genre-adventure",
        target: "all" as const,
        hashtags: [],
        visibility: "public" as const,
      },
    };
  }

  it("requires at least one starting setup", () => {
    const empty = storyBuilderSchema.safeParse({ ...validFullForm(), startingSetups: [] });
    const withOne = storyBuilderSchema.safeParse(validFullForm());

    expect(empty.success).toBe(false);
    expect(withOne.success).toBe(true);
  });

  it("defaults keywordNotes/shortcuts to empty arrays when omitted", () => {
    const result = storyBuilderSchema.safeParse(validFullForm());

    expect(result.success).toBe(true);
    expect(result.success && result.data.keywordNotes).toEqual([]);
    expect(result.success && result.data.shortcuts).toEqual([]);
  });
});
