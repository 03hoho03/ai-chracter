import { describe, expect, it } from "vitest";

import {
  endingSchema,
  keywordNoteSchema,
  MAX_MEDIA_BOOK_CELLS,
  MAX_MEDIA_BOOK_NAME_LENGTH,
  mediaBookAxisSchema,
  mediaBookCellSchema,
  mediaBookSchema,
  normalizeKeyword,
  ruleListItemSchema,
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

  it("never requires developmentExamples/userGoal/rules regardless of promptTemplate", () => {
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

  it("accepts userGoal/rules as optional free text", () => {
    const result = storySettingSchema.safeParse({
      promptTemplate: "basic",
      worldSetting: "세계관 설명",
      userGoal: "사용자는 새로 부임한 주방장이다. 손님들의 신뢰를 얻는 것이 목표다.",
      rules: "손님의 정체는 먼저 밝히지 않는다.",
    });

    expect(result.success).toBe(true);
    expect(result.success && result.data.userGoal).toBe(
      "사용자는 새로 부임한 주방장이다. 손님들의 신뢰를 얻는 것이 목표다.",
    );
    expect(result.success && result.data.rules).toBe("손님의 정체는 먼저 밝히지 않는다.");
  });

  it("defaults developmentExamples to an empty array when omitted", () => {
    const result = storySettingSchema.safeParse({
      promptTemplate: "basic",
      worldSetting: "세계관 설명",
    });

    expect(result.success).toBe(true);
    expect(result.success && result.data.developmentExamples).toEqual([]);
  });

  it("accepts up to 3 development example pairs", () => {
    const threePairs = Array.from({ length: 3 }, (_, i) => ({
      userLine: `사용자 메시지 ${i}`,
      assistantLine: `스토리 응답 ${i}`,
    }));

    const result = storySettingSchema.safeParse({
      promptTemplate: "basic",
      worldSetting: "세계관 설명",
      developmentExamples: threePairs,
    });

    expect(result.success).toBe(true);
  });

  it("rejects a 4th development example pair", () => {
    const fourPairs = Array.from({ length: 4 }, (_, i) => ({
      userLine: `사용자 메시지 ${i}`,
      assistantLine: `스토리 응답 ${i}`,
    }));

    const result = storySettingSchema.safeParse({
      promptTemplate: "basic",
      worldSetting: "세계관 설명",
      developmentExamples: fourPairs,
    });

    expect(result.success).toBe(false);
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

  it("requires icon and color", () => {
    const missingIcon = statDefSchema.safeParse({ ...validStatDef(), icon: "" });
    const missingColor = statDefSchema.safeParse({ ...validStatDef(), color: "" });

    expect(missingIcon.success).toBe(false);
    expect(missingColor.success).toBe(false);
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

  it("accepts up to 4 suggested replies", () => {
    const fourReplies = Array.from({ length: 4 }, (_, i) => `추천 답변 ${i}`);

    const result = startingSetupSchema.safeParse({
      ...validStartingSetup(),
      suggestedReplies: fourReplies,
    });

    expect(result.success).toBe(true);
  });

  it("rejects a 5th suggested reply", () => {
    const fiveReplies = Array.from({ length: 5 }, (_, i) => `추천 답변 ${i}`);

    const result = startingSetupSchema.safeParse({
      ...validStartingSetup(),
      suggestedReplies: fiveReplies,
    });

    expect(result.success).toBe(false);
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

  it("accepts content up to the length limit and rejects one character more", () => {
    const atLimit = keywordNoteSchema.safeParse({ ...validKeywordNote(), content: "가".repeat(800) });
    const overLimit = keywordNoteSchema.safeParse({ ...validKeywordNote(), content: "가".repeat(801) });

    expect(atLimit.success).toBe(true);
    expect(overLimit.success).toBe(false);
  });

  it("accepts up to 10 trigger keywords and rejects the 11th", () => {
    const keywords = (count: number) => Array.from({ length: count }, (_, i) => `키워드${i}`);

    expect(keywordNoteSchema.safeParse({ ...validKeywordNote(), triggerKeywords: keywords(10) }).success).toBe(true);
    expect(keywordNoteSchema.safeParse({ ...validKeywordNote(), triggerKeywords: keywords(11) }).success).toBe(false);
  });

  it("accepts a 20-character trigger keyword and rejects a 21-character one", () => {
    const atLimit = keywordNoteSchema.safeParse({ ...validKeywordNote(), triggerKeywords: ["가".repeat(20)] });
    const overLimit = keywordNoteSchema.safeParse({ ...validKeywordNote(), triggerKeywords: ["가".repeat(21)] });

    expect(atLimit.success).toBe(true);
    expect(overLimit.success).toBe(false);
  });

  it("rejects a whitespace-only trigger keyword", () => {
    const result = keywordNoteSchema.safeParse({ ...validKeywordNote(), triggerKeywords: ["밤", "  "] });

    expect(result.success).toBe(false);
  });

  it.each([
    ["letter case", "USB", "usb"],
    ["Unicode composition", "한밤", "한밤".normalize("NFD")],
    ["sharp s that the server folds to ss", "straße", "STRASSE"],
  ])("rejects trigger keywords that differ only by %s", (_, first, second) => {
    const result = keywordNoteSchema.safeParse({ ...validKeywordNote(), triggerKeywords: [first, second] });

    expect(result.success).toBe(false);
    // 배열 자리에 실어야 화면의 키워드 오류 한 줄에 보인다(원소 자리 오류는 표시할 곳이 없다).
    expect(result.success ? [] : result.error.issues.map((issue) => issue.path)).toContainEqual(["triggerKeywords"]);
  });
});

describe("normalizeKeyword", () => {
  it("folds letter case and Unicode composition the way the server compares keywords", () => {
    expect(normalizeKeyword("USB")).toBe("usb");
    expect(normalizeKeyword("한밤".normalize("NFD"))).toBe("한밤");
    // 파이썬 casefold 는 ß·ẞ 를 ss 로 접는다 — 소문자화만으로는 이 둘이 서버보다 느슨해진다.
    expect(normalizeKeyword("ẞ")).toBe(normalizeKeyword("ss"));
    expect(normalizeKeyword("ß")).toBe(normalizeKeyword("SS"));
  });
});

describe("storyBuilderSchema keywordNotes", () => {
  function notes(count: number) {
    return Array.from({ length: count }, (_, i) => ({
      id: `note-${i}`,
      content: `표지 ${i}`,
      triggerKeywords: [`키워드${i}`],
      scope: { kind: "global" as const },
    }));
  }

  it("accepts up to 50 keyword notes and rejects the 51st", () => {
    expect(storyBuilderSchema.safeParse({ ...validFullForm(), keywordNotes: notes(50) }).success).toBe(true);
    expect(storyBuilderSchema.safeParse({ ...validFullForm(), keywordNotes: notes(51) }).success).toBe(false);
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

function singleRule(overrides: Partial<Record<string, unknown>> = {}) {
  return { kind: "rule", id: "rule-1", statId: "stat-1", operator: ">=", value: 50, nextOp: null, ...overrides };
}

describe("ruleListItemSchema", () => {
  it("accepts a single rule", () => {
    expect(ruleListItemSchema.safeParse(singleRule()).success).toBe(true);
  });

  it("accepts a group containing only single rules", () => {
    const result = ruleListItemSchema.safeParse({
      kind: "group",
      id: "group-1",
      nextOp: null,
      rules: [singleRule({ id: "rule-a" }), singleRule({ id: "rule-b", nextOp: "or" })],
    });

    expect(result.success).toBe(true);
  });

  it("rejects a group nested inside another group (no nesting)", () => {
    const result = ruleListItemSchema.safeParse({
      kind: "group",
      id: "group-1",
      nextOp: null,
      rules: [{ kind: "group", id: "group-2", nextOp: null, rules: [singleRule()] }],
    });

    expect(result.success).toBe(false);
  });

  it("rejects the '!=' operator (server EndingRuleOperator has no not-equal value)", () => {
    const result = ruleListItemSchema.safeParse(singleRule({ operator: "!=" }));

    expect(result.success).toBe(false);
  });

  it("accepts the other 5 comparison operators", () => {
    for (const operator of [">", ">=", "<", "<=", "=="]) {
      expect(ruleListItemSchema.safeParse(singleRule({ operator })).success).toBe(true);
    }
  });
});

describe("endingSchema", () => {
  function validEnding() {
    return {
      id: "ending-1",
      name: "함께 살아남기",
      turnGate: 10,
      judgePrompt: "주인공들이 서로를 구조했는지 판정",
    };
  }

  it("requires turnGate to be at least 10", () => {
    const belowMin = endingSchema.safeParse({ ...validEnding(), turnGate: 9 });
    const atMin = endingSchema.safeParse({ ...validEnding(), turnGate: 10 });

    expect(belowMin.success).toBe(false);
    expect(atMin.success).toBe(true);
  });

  it("defaults statRules to an empty array (judgePrompt만으로 판정)", () => {
    const result = endingSchema.safeParse(validEnding());

    expect(result.success).toBe(true);
    expect(result.success && result.data.statRules).toEqual([]);
  });

  it("makes epilogue/hint optional", () => {
    const result = endingSchema.safeParse(validEnding());

    expect(result.success).toBe(true);
    expect(result.success && result.data.epilogue).toBeUndefined();
    expect(result.success && result.data.hint).toBeUndefined();
  });

  it("requires name/judgePrompt", () => {
    expect(endingSchema.safeParse({ ...validEnding(), name: "" }).success).toBe(false);
    expect(endingSchema.safeParse({ ...validEnding(), judgePrompt: "" }).success).toBe(false);
  });
});

function validFullForm() {
  return {
    profile: {
      name: "여름밤의 항해",
      oneLiner: "바다 위 표류기",
      image: { assetId: "asset-thumbnail-1" },
    },
    storySetting: { promptTemplate: "basic" as const, worldSetting: "근미래 해양 도시" },
    startingSetups: [validStartingSetup()],
    mediaBook: { people: [], scenes: [], cells: [] },
    registration: {
      description: "표류한 선원들의 생존기",
      genre: "genre-adventure",
      target: "all" as const,
      hashtags: [],
      visibility: "public" as const,
    },
  };
}

describe("storyBuilderSchema startingSetups", () => {
  it("requires at least one starting setup", () => {
    const empty = storyBuilderSchema.safeParse({ ...validFullForm(), startingSetups: [] });
    const withOne = storyBuilderSchema.safeParse(validFullForm());

    expect(empty.success).toBe(false);
    expect(withOne.success).toBe(true);
  });

  it("accepts up to 4 starting setups", () => {
    const fourSetups = Array.from({ length: 4 }, (_, i) => ({
      ...validStartingSetup(),
      id: `setup-${i}`,
    }));

    const result = storyBuilderSchema.safeParse({ ...validFullForm(), startingSetups: fourSetups });

    expect(result.success).toBe(true);
  });

  it("rejects a 5th starting setup", () => {
    const fiveSetups = Array.from({ length: 5 }, (_, i) => ({
      ...validStartingSetup(),
      id: `setup-${i}`,
    }));

    const result = storyBuilderSchema.safeParse({ ...validFullForm(), startingSetups: fiveSetups });

    expect(result.success).toBe(false);
  });

  it("defaults keywordNotes/shortcuts to empty arrays when omitted", () => {
    const result = storyBuilderSchema.safeParse(validFullForm());

    expect(result.success).toBe(true);
    expect(result.success && result.data.keywordNotes).toEqual([]);
    expect(result.success && result.data.shortcuts).toEqual([]);
  });
});

/** 초안을 담으려고 nullable로 둔 3필드는 화면에 `*`가
 * 붙어 있고 서버도 요구한다. 타입은 그대로 두고 refine이 상시 검증해 서버 400 왕복 전에 걸린다. */
describe("storyBuilderSchema publish-required nullable fields", () => {
  it("rejects a null profile.image", () => {
    const result = storyBuilderSchema.safeParse({
      ...validFullForm(),
      profile: { ...validFullForm().profile, image: null },
    });

    expect(result.success).toBe(false);
    expect(result.success ? [] : result.error.issues.map((issue) => issue.path)).toContainEqual([
      "profile",
      "image",
    ]);
  });

  it("rejects a null registration.genre", () => {
    const result = storyBuilderSchema.safeParse({
      ...validFullForm(),
      registration: { ...validFullForm().registration, genre: null },
    });

    expect(result.success).toBe(false);
    expect(result.success ? [] : result.error.issues.map((issue) => issue.path)).toContainEqual([
      "registration",
      "genre",
    ]);
  });

  it("rejects a null registration.target", () => {
    const result = storyBuilderSchema.safeParse({
      ...validFullForm(),
      registration: { ...validFullForm().registration, target: null },
    });

    expect(result.success).toBe(false);
    expect(result.success ? [] : result.error.issues.map((issue) => issue.path)).toContainEqual([
      "registration",
      "target",
    ]);
  });

  it("reports all three at once (누락 토스트가 한 번에 나열할 수 있어야 한다)", () => {
    const form = validFullForm();
    const result = storyBuilderSchema.safeParse({
      ...form,
      profile: { ...form.profile, image: null },
      registration: { ...form.registration, genre: null, target: null },
    });

    const paths = result.success ? [] : result.error.issues.map((issue) => issue.path);
    expect(paths).toContainEqual(["profile", "image"]);
    expect(paths).toContainEqual(["registration", "genre"]);
    expect(paths).toContainEqual(["registration", "target"]);
  });

  it("passes once all three are filled", () => {
    expect(storyBuilderSchema.safeParse(validFullForm()).success).toBe(true);
  });
});

/** 서버가 받는 uuid 모양 id. `prefix` 는 16진 한 글자라 종류별로 겹치지 않는다. */
function guid(prefix: string, index: number): string {
  return `00000000-0000-4000-8000-${prefix}${String(index).padStart(11, "0")}`;
}

const SCENE_ID = guid("b", 0);

describe("mediaBookAxisSchema", () => {
  function nameIssues(name: string) {
    const result = mediaBookAxisSchema.safeParse({ id: "00000000-0000-4000-8000-0000000000a1", name });
    return result.success ? [] : result.error.issues.map((issue) => issue.path);
  }

  it.each([
    ["one character", "에"],
    ["exactly the limit", "가".repeat(MAX_MEDIA_BOOK_NAME_LENGTH)],
    ["the limit plus surrounding spaces the server trims", `  ${"가".repeat(MAX_MEDIA_BOOK_NAME_LENGTH)}  `],
    ["emoji counted as one character each like the server", "😀".repeat(MAX_MEDIA_BOOK_NAME_LENGTH)],
    ["a decomposed (NFD) name measured after NFC like the server", "가".normalize("NFD").repeat(MAX_MEDIA_BOOK_NAME_LENGTH)],
  ])("accepts %s", (_label, name) => {
    expect(nameIssues(name)).toEqual([]);
  });

  it.each([
    ["an empty name", ""],
    ["a whitespace-only name", "   "],
    ["one character over the limit", "가".repeat(MAX_MEDIA_BOOK_NAME_LENGTH + 1)],
    ["a slash", "에리/준"],
    ["an opening brace", "에리{"],
    ["a closing brace", "에리}"],
    ["a colon", "에리:"],
  ])("rejects %s", (_label, name) => {
    expect(nameIssues(name)).toContainEqual(["name"]);
  });
});

describe("mediaBookCellSchema", () => {
  function validCell() {
    return {
      id: "00000000-0000-4000-8000-0000000000c1",
      personId: "00000000-0000-4000-8000-0000000000a1",
      sceneId: "00000000-0000-4000-8000-0000000000b1",
      imageAssetId: "00000000-0000-4000-8000-0000000000d1",
      situationDescription: "",
      unlockHint: "",
      excludeFromChat: false,
    };
  }

  it("accepts a situation description of 100 characters and an unlock hint of 20", () => {
    const result = mediaBookCellSchema.safeParse({
      ...validCell(),
      situationDescription: "가".repeat(100),
      unlockHint: "가".repeat(20),
    });

    expect(result.success).toBe(true);
  });

  it("rejects a situation description of 101 characters", () => {
    const result = mediaBookCellSchema.safeParse({ ...validCell(), situationDescription: "가".repeat(101) });

    expect(result.success ? [] : result.error.issues.map((issue) => issue.path)).toContainEqual([
      "situationDescription",
    ]);
  });

  it("rejects an unlock hint of 21 characters", () => {
    const result = mediaBookCellSchema.safeParse({ ...validCell(), unlockHint: "가".repeat(21) });

    expect(result.success ? [] : result.error.issues.map((issue) => issue.path)).toContainEqual(["unlockHint"]);
  });
});

describe("mediaBookSchema", () => {
  // 칸마다 다른 인물 줄에 둬 같은 자리 중복 검사에 걸리지 않게 한다.
  function mediaBookWithCells(count: number) {
    const people = Array.from({ length: count }, (_, index) => ({ id: guid("a", index), name: `인물${index}` }));
    return {
      people,
      scenes: [{ id: SCENE_ID, name: "기쁨" }],
      cells: people.map((person, index) => ({
        id: guid("c", index),
        personId: person.id,
        sceneId: SCENE_ID,
        imageAssetId: guid("d", index),
        situationDescription: "",
        unlockHint: "",
        excludeFromChat: false,
      })),
    };
  }

  it("accepts exactly the cell limit", () => {
    expect(mediaBookSchema.safeParse(mediaBookWithCells(MAX_MEDIA_BOOK_CELLS)).success).toBe(true);
  });

  it("rejects one cell over the limit", () => {
    const result = mediaBookSchema.safeParse(mediaBookWithCells(MAX_MEDIA_BOOK_CELLS + 1));

    expect(result.success ? [] : result.error.issues.map((issue) => issue.path)).toContainEqual(["cells"]);
  });

  function issuePaths(value: unknown) {
    const result = mediaBookSchema.safeParse(value);
    return result.success ? [] : result.error.issues.map((issue) => issue.path);
  }

  // `index` 번째 인물 줄 × 첫 장면에 놓인 칸.
  function cellAt(index: number, overrides: Partial<{ id: string; personId: string; imageAssetId: string }> = {}) {
    return {
      id: guid("c", index),
      personId: guid("a", index),
      sceneId: SCENE_ID,
      imageAssetId: guid("d", index),
      situationDescription: "",
      unlockHint: "",
      excludeFromChat: false,
      ...overrides,
    };
  }

  function twoCellBook() {
    return {
      people: [
        { id: guid("a", 0), name: "에리" },
        { id: guid("a", 1), name: "준" },
      ],
      scenes: [{ id: SCENE_ID, name: "기쁨" }],
      cells: [cellAt(0), cellAt(1)],
    };
  }

  it("accepts the same name on a person and a scene (names are unique per axis only)", () => {
    expect(issuePaths({ ...twoCellBook(), scenes: [{ id: SCENE_ID, name: "에리" }] })).toEqual([]);
  });

  it("rejects an axis id that is not a uuid", () => {
    const book = { ...twoCellBook(), people: [{ id: "person-1", name: "에리" }] };

    expect(issuePaths(book)).toContainEqual(["people", 0, "id"]);
  });

  it.each([
    ["cell id", { id: "cell-1" }, "id"],
    ["image asset id", { imageAssetId: "asset-1" }, "imageAssetId"],
  ] as const)("rejects a %s that is not a uuid", (_label, overrides, field) => {
    const book = { ...twoCellBook(), cells: [cellAt(0, overrides), cellAt(1)] };

    expect(issuePaths(book)).toContainEqual(["cells", 0, field]);
  });

  it.each([
    ["the same name", "에리"],
    ["a name equal after trimming", " 에리 "],
    ["a name equal after NFC", "에리".normalize("NFD")],
  ])("rejects a second person with %s", (_label, name) => {
    const book = {
      ...twoCellBook(),
      people: [
        { id: guid("a", 0), name: "에리" },
        { id: guid("a", 1), name },
      ],
    };

    expect(issuePaths(book)).toContainEqual(["people", 1, "name"]);
  });

  it("rejects a repeated scene name", () => {
    const book = {
      ...twoCellBook(),
      scenes: [
        { id: SCENE_ID, name: "기쁨" },
        { id: guid("b", 1), name: "기쁨" },
      ],
    };

    expect(issuePaths(book)).toContainEqual(["scenes", 1, "name"]);
  });

  it("rejects a repeated axis id", () => {
    const book = {
      ...twoCellBook(),
      people: [
        { id: guid("a", 0), name: "에리" },
        { id: guid("a", 0), name: "준" },
      ],
      cells: [cellAt(0)],
    };

    expect(issuePaths(book)).toContainEqual(["people", 1, "id"]);
  });

  it("rejects a repeated cell id", () => {
    const book = { ...twoCellBook(), cells: [cellAt(0), cellAt(1, { id: guid("c", 0) })] };

    expect(issuePaths(book)).toContainEqual(["cells", 1, "id"]);
  });

  it("rejects a cell pointing at a person that is not in the media book", () => {
    const book = { ...twoCellBook(), cells: [cellAt(0), cellAt(1, { personId: guid("a", 9) })] };

    expect(issuePaths(book)).toContainEqual(["cells", 1]);
  });

  it("rejects two cells at the same person × scene", () => {
    const book = { ...twoCellBook(), cells: [cellAt(0), cellAt(1, { personId: guid("a", 0) })] };

    expect(issuePaths(book)).toContainEqual(["cells", 1]);
  });
});
