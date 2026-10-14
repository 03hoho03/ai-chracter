import { describe, expect, it } from "vitest";

import {
  createEmptyDraft,
  MAX_DEVELOPMENT_EXAMPLES,
  MAX_HASHTAGS,
  MAX_NAME_LENGTH,
  MAX_STARTING_SETUPS,
  MAX_SUGGESTED_REPLIES,
} from "@/entities/content";
import { fieldLabelForPath, matchTabForPath, publishIssueRows } from "@/features/build-common";
import {
  MAX_EXCLUDE_KEYWORDS,
  MAX_KEYWORD_NOTE_NAME_LENGTH,
  MAX_KEYWORD_NOTES,
  MAX_MEDIA_BOOK_CELLS,
  MAX_SITUATION_NOTE_NAME_LENGTH,
  MAX_SITUATION_NOTES,
  MAX_STAT_RULES,
  serverToForm,
  storyBuilderSchema,
  STORY_FIELD_LABELS,
  STORY_MISSING_FIELD_LABELS,
  storyMissingFieldFormPath,
  storyMissingFieldServerLabel,
  STORY_TABS,
} from "@/features/build-story";

// 발행 전 확인 목록이 스토리 발행 검사의 모든 오류 경로에 칸 이름을 붙이는지 전수로 본다 — 셸과 같은 라벨 함수(칸 라벨 표에서
// 찾기)를 쓴다. 빈 초안과 대표적인 틀린 값을 넣어 나온 경로 전부가 대상이다.

const PERSON = "11111111-1111-4111-8111-111111111111";
const SCENE = "22222222-2222-4222-8222-222222222222";
const ASSET = "33333333-3333-4333-8333-333333333333";

function stat(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    name: "체력",
    icon: "heart",
    color: "rose",
    min: 0,
    max: 100,
    initial: 50,
    unit: "",
    description: "생존에 필요한 신체 상태",
    perTurnDelta: null,
    rules: [{ id: `${id}-rule`, condition: "물을 마셨다", delta: 3 }],
    ...overrides,
  };
}

function rule(statId: string) {
  return { kind: "rule", id: `rule-${statId}`, statId, operator: ">", value: 1, nextOp: null };
}

function setup(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    name: "표류 첫날",
    prologue: "배가 좌초되고 눈을 뜨니 낯선 해변이다.",
    openingSituation: "",
    playGuide: "",
    suggestedReplies: [],
    stats: [stat(`${id}-stat`)],
    endings: [],
    situationNotes: [],
    ...overrides,
  };
}

function keywordNote(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    content: "섬의 동쪽에는 등대가 있다",
    triggerKeywords: ["등대"],
    scope: { kind: "global" },
    name: "",
    excludeKeywords: [],
    stickyTurns: 0,
    alwaysOn: false,
    ...overrides,
  };
}

function validStory() {
  return {
    profile: { image: { assetId: "asset-1" }, name: "여름밤의 항해", oneLiner: "바다 위 표류기" },
    storySetting: {
      promptTemplate: "basic",
      worldSetting: "근미래 해양 도시",
      userGoal: "",
      rules: "",
      customPrompt: "",
      developmentExamples: [],
    },
    startingSetups: [setup("setup-1")],
    keywordNotes: [],
    shortcuts: [],
    mediaBook: { people: [], scenes: [], cells: [] },
    registration: {
      description: "표류한 선원들의 생존기",
      genre: "genre-adventure",
      target: "all",
      hashtags: [],
      visibility: "public",
      novelPermission: "private",
    },
  };
}

function emptyStory() {
  const draft = createEmptyDraft("story");
  if (draft.type !== "story") throw new Error("스토리 빈 초안이 아니에요.");
  return serverToForm(draft);
}

const many = <T,>(count: number, make: (index: number) => T): T[] => Array.from({ length: count }, (_, i) => make(i));

/** 이름 → 발행 검사에 넣을 값. 뒤의 것일수록 한 칸에 여러 위반을 겹친다. */
const SCENARIOS: Record<string, unknown> = {
  "빈 초안": emptyStory(),
  [`시작설정 ${MAX_STARTING_SETUPS + 1}개`]: {
    ...validStory(),
    startingSetups: many(MAX_STARTING_SETUPS + 1, (i) => setup(`setup-${i}`)),
  },
  "시작설정 이름·프롤로그 빈 값·추천 답변 초과": {
    ...validStory(),
    startingSetups: [
      setup("setup-1", { name: " ", prologue: "", suggestedReplies: many(MAX_SUGGESTED_REPLIES + 1, (i) => `답 ${i}`) }),
    ],
  },
  "커스텀 템플릿 빈 프롬프트·전개 예시 초과": {
    ...validStory(),
    storySetting: {
      ...validStory().storySetting,
      promptTemplate: "custom",
      customPrompt: "",
      developmentExamples: many(MAX_DEVELOPMENT_EXAMPLES + 1, () => ({ userLine: "a", assistantLine: "b" })),
    },
  },
  "스탯 빈 칸·범위·규칙": {
    ...validStory(),
    startingSetups: [
      setup("setup-1", {
        stats: [
          stat("s-blank", { name: "", icon: "", color: "", description: "", min: Number.NaN, max: Number.NaN, initial: Number.NaN }),
          stat("s-range", { min: 10, max: 5, initial: 50, perTurnDelta: 1.5 }),
          stat("s-initial", { min: 0, max: 10, initial: 50 }),
          stat("s-norules", { rules: [] }),
          stat("s-counter", { perTurnDelta: -1 }),
          stat("s-badrule", {
            rules: [
              { id: "r1", condition: "", delta: 0 },
              { id: "r1", condition: "x".repeat(200), delta: 999 },
            ],
          }),
          stat("s-manyrules", { rules: many(MAX_STAT_RULES + 1, (i) => ({ id: `r${i}`, condition: "c", delta: 1 })) }),
        ],
      }),
    ],
  },
  "엔딩 빈 칸·턴 미달·지워진 스탯 조건": {
    ...validStory(),
    startingSetups: [
      setup("setup-1", {
        endings: [
          {
            id: "e1",
            name: "",
            turnGate: 5,
            judgePrompt: "",
            statRules: [rule("deleted-stat"), { kind: "group", id: "g1", rules: [rule("deleted-stat")], nextOp: null }],
            priorityStatId: "deleted-stat",
          },
        ],
      }),
    ],
  },
  "상황 노트 조건 없음·빈 상황·이름 초과·개수 초과": {
    ...validStory(),
    startingSetups: [
      setup("setup-1", {
        situationNotes: many(MAX_SITUATION_NOTES + 1, (i) => ({
          id: `n${i}`,
          name: "가".repeat(MAX_SITUATION_NOTE_NAME_LENGTH + 1),
          content: i === 0 ? " " : "상황",
          conditionRules: i === 0 ? [] : [rule("deleted-stat")],
        })),
      }),
    ],
  },
  "키워드 노트 빈 정보·트리거 없음·옵션 위반": {
    ...validStory(),
    keywordNotes: [
      keywordNote("k1", { content: "", triggerKeywords: [] }),
      keywordNote("k2", {
        triggerKeywords: [""],
        excludeKeywords: many(MAX_EXCLUDE_KEYWORDS + 1, (i) => `금지${i}`),
        name: "가".repeat(MAX_KEYWORD_NOTE_NAME_LENGTH + 1),
        stickyTurns: 99,
        scope: { kind: "startingSetup" },
      }),
    ],
  },
  "상시 적용 4개": {
    ...validStory(),
    keywordNotes: many(4, (i) => keywordNote(`k${i}`, { alwaysOn: true, triggerKeywords: [] })),
  },
  [`키워드 노트 ${MAX_KEYWORD_NOTES + 1}개`]: {
    ...validStory(),
    keywordNotes: many(MAX_KEYWORD_NOTES + 1, (i) => keywordNote(`k${i}`)),
  },
  "단축어 빈 칸": {
    ...validStory(),
    shortcuts: [{ id: "sc1", name: "", description: "", prompt: "" }],
  },
  "미디어 북 빈 이름·중복·끊긴 칸·칸 초과": {
    ...validStory(),
    mediaBook: {
      people: [
        { id: PERSON, name: "" },
        { id: PERSON, name: "" },
      ],
      scenes: [{ id: SCENE, name: "a/b" }],
      cells: many(MAX_MEDIA_BOOK_CELLS + 1, () => ({
        id: ASSET,
        personId: "44444444-4444-4444-8444-444444444444",
        sceneId: SCENE,
        imageAssetId: ASSET,
        situationDescription: "",
        unlockHint: "",
        excludeFromChat: false,
      })),
    },
  },
  "해시태그 초과·이름 길이 초과": {
    ...validStory(),
    profile: { ...validStory().profile, name: "가".repeat(MAX_NAME_LENGTH + 1) },
    registration: { ...validStory().registration, hashtags: many(MAX_HASHTAGS + 1, (i) => `태그${i}`) },
  },
};

function issuePaths(value: unknown): string[] {
  const result = storyBuilderSchema.safeParse(value);
  return result.success ? [] : result.error.issues.map((issue) => issue.path.map(String).join("."));
}

const labelFor = (path: string) => fieldLabelForPath(path, STORY_FIELD_LABELS);

describe("스토리 발행 전 확인 목록 라벨 전수", () => {
  it("기준 값은 오류가 없다(아래 시나리오의 오류가 넣은 위반에서만 나온다)", () => {
    expect(issuePaths(validStory())).toEqual([]);
  });

  it.each(Object.entries(SCENARIOS))("%s — 모든 오류 경로에 칸 이름과 탭이 있다", (_name, value) => {
    const paths = issuePaths(value);
    expect(paths.length).toBeGreaterThan(0);
    for (const path of paths) {
      expect({ path, label: labelFor(path), tab: matchTabForPath(path, STORY_TABS) }).toEqual({
        path,
        label: expect.any(String),
        tab: expect.any(String),
      });
    }
    const rows = publishIssueRows(paths, STORY_TABS, labelFor);
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) expect(row.label).not.toMatch(/그 밖의/);
  });

  it("칸 이름은 탭 이름 뒤에 부모 항목 순번과 함께 붙고, 탭 이름으로 시작하면 탭 이름을 다시 붙이지 않는다", () => {
    const rows = publishIssueRows(
      [
        "startingSetups.0.prologue",
        "keywordNotes",
        "keywordNotes.0.triggerKeywords",
        "startingSetups.0.stats.1.max",
        "startingSetups",
        "mediaBook.cells.3",
      ],
      STORY_TABS,
      labelFor,
    );
    expect(rows.map((row) => row.label)).toEqual([
      "1번째 시작설정 프롤로그",
      "시작설정",
      "스탯 · 1번째 시작설정 2번째 스탯 최대값",
      "미디어 북 · 4번째 칸",
      "키워드북",
      "키워드북 · 1번째 노트 트리거 키워드",
    ]);
  });
});

describe("스토리 서버 400 키 라벨 전수", () => {
  const INDEXED_KEYS = ["startingSetups[0].name", "startingSetups[1].prologue", "startingSetups[0].endings[2].turnCountGate"];

  it.each([...Object.keys(STORY_MISSING_FIELD_LABELS), ...INDEXED_KEYS])("%s 는 칸에 걸리고 목록 줄 이름이 있다", (field) => {
    const path = storyMissingFieldFormPath(field);
    expect(path).toEqual(expect.any(String));
    const serverLabel = storyMissingFieldServerLabel(field);
    // 서버 라벨을 쓰지 않는 키(칸을 짚는 키·인덱스 키)는 칸 라벨 표에서 이름을 찾아야 한다.
    if (serverLabel === undefined) expect(labelFor(path ?? "")).toEqual(expect.any(String));
    const rows = publishIssueRows([path ?? ""], STORY_TABS, (target) => serverLabel ?? labelFor(target));
    expect(rows).toHaveLength(1);
    expect(rows[0]?.label).not.toMatch(/그 밖의/);
  });

  it("인덱스 키는 칸 라벨 표로 이름을 찾는다", () => {
    const path = storyMissingFieldFormPath("startingSetups[0].endings[2].turnCountGate") ?? "";
    expect(publishIssueRows([path], STORY_TABS, labelFor).map((row) => row.label)).toEqual([
      "엔딩 · 1번째 시작설정 3번째 엔딩 엔딩조건 (최소 턴수)",
    ]);
  });
});
