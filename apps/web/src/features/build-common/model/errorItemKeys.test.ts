import type { FieldErrors } from "react-hook-form";
import { describe, expect, it } from "vitest";

import type { BuilderTab } from "@/entities/content";

import { errorItemKeys, type CollapsibleListSpec } from "./errorItemKeys";

/** `features/build-story` 의 `STORY_TABS`·`STORY_COLLAPSIBLE_LISTS` 를 값 그대로 옮긴 픽스처. features 슬라이스끼리
 * import 하지 않으려고 리터럴로 다시 적는다(`errorTabs.test.ts` 와 같은 이유). 겹치는 접두(`startingSetups` ↔
 * `startingSetups.*.stats`)가 검증 대상이라 줄이지 않는다. */
const STORY_TABS: readonly BuilderTab[] = [
  { id: "profile", label: "프로필", fields: ["profile"], preview: "card" },
  { id: "setting", label: "설정", fields: ["storySetting"], preview: "chat" },
  { id: "startingSetup", label: "시작설정", fields: ["startingSetups"], preview: "chat" },
  { id: "stat", label: "스탯", fields: ["startingSetups.*.stats"], preview: "chat" },
  { id: "mediaBook", label: "미디어 북", fields: ["mediaBook"], preview: "chat" },
  { id: "keywordNote", label: "키워드북", fields: ["keywordNotes"], preview: "chat" },
  { id: "shortcut", label: "단축어", fields: ["shortcuts"], preview: "chat" },
  { id: "ending", label: "엔딩", fields: ["startingSetups.*.endings"], preview: "chat" },
  { id: "registration", label: "등록", fields: ["registration"], preview: "card" },
];

const STORY_LISTS: Record<string, CollapsibleListSpec> = {
  developmentExample: { path: "storySetting.developmentExamples", tabId: "setting", key: "index" },
  startingSetup: { path: "startingSetups", tabId: "startingSetup", key: "id" },
  stat: { path: "startingSetups.*.stats", tabId: "stat", key: "id" },
  keywordNote: { path: "keywordNotes", tabId: "keywordNote", key: "id" },
  shortcut: { path: "shortcuts", tabId: "shortcut", key: "id" },
  ending: { path: "startingSetups.*.endings", tabId: "ending", key: "id" },
  ruleGroup: { path: "startingSetups.*.endings.*.statRules", tabId: "ending", key: "id" },
};

const CHARACTER_TABS: readonly BuilderTab[] = [
  { id: "profile", label: "프로필", fields: ["profile"], preview: "card" },
  { id: "intro", label: "인트로", fields: ["intro"], preview: "chat" },
  { id: "prompt", label: "프롬프트", fields: ["prompt"], preview: "chat" },
  { id: "advanced", label: "상황별 이미지", fields: ["situationalImages"], preview: "chat" },
  { id: "detail", label: "등록", fields: ["registration"], preview: "card" },
];

const CHARACTER_LISTS: Record<string, CollapsibleListSpec> = {
  exampleDialogue: { path: "intro.exampleDialogues", tabId: "intro", key: "id" },
  situationalImage: { path: "situationalImages", tabId: "advanced", key: "id" },
};

/** 픽스처가 쓰는 폼 경로만 담은 지역 타입(실제 폼 타입은 다른 features 슬라이스에 있다). */
type RuleFixture = { id: string; kind: string; value?: number; rules?: RuleFixture[] };
type StoryFixture = {
  profile: { name: string };
  storySetting: { developmentExamples: { userLine: string; assistantLine: string }[] };
  startingSetups: {
    id: string;
    name: string;
    stats: { id: string; name?: string; min?: number }[];
    endings: { id: string; name?: string; statRules: RuleFixture[] }[];
  }[];
  keywordNotes: { id: string; name?: string; content?: string; scope?: string }[];
  shortcuts: { id: string | number; name?: string }[];
};
type CharacterFixture = {
  intro: { exampleDialogues: { id: string; userLine?: string }[] };
  situationalImages: { id: string; situationDescription?: string }[];
};

/** 시작설정 둘(각 스탯 둘·엔딩 하나, 엔딩 규칙 = 단일 규칙 + 그룹), 키워드 셋, 단축어 셋, 전개 예시 둘. id 는 인덱스와
 * 일부러 다른 글자로 둬서 인덱스를 키로 쓰면 드러나게 한다. */
const STORY_VALUES: StoryFixture = {
  profile: { name: "" },
  storySetting: { developmentExamples: [{ userLine: "", assistantLine: "" }, { userLine: "", assistantLine: "" }] },
  startingSetups: [
    {
      id: "setup-a",
      name: "",
      stats: [{ id: "stat-a1" }, { id: "stat-a2" }],
      endings: [{ id: "ending-a1", statRules: [{ id: "rule-a1", kind: "rule" }] }],
    },
    {
      id: "setup-b",
      name: "",
      stats: [{ id: "stat-b1" }, { id: "stat-b2" }],
      endings: [
        {
          id: "ending-b1",
          statRules: [
            { id: "rule-b1", kind: "rule" },
            { id: "group-b2", kind: "group", rules: [{ id: "rule-b2-1", kind: "rule" }] },
          ],
        },
      ],
    },
  ],
  keywordNotes: [{ id: "note-x" }, { id: "note-y" }, { id: "note-z" }],
  shortcuts: [{ id: "short-x" }, { id: "short-y" }, { id: "short-z" }],
};

function fieldError(message = "필수 항목이에요."): { type: string; message: string } {
  return { type: "custom", message };
}

function storyKeys(errors: FieldErrors<StoryFixture>): string[] {
  return [...errorItemKeys(errors, STORY_VALUES, STORY_LISTS, STORY_TABS)].sort();
}

describe("errorItemKeys", () => {
  it("항목 필드 오류는 인덱스가 아니라 그 항목 값의 id 로 키를 만든다", () => {
    expect(storyKeys({ keywordNotes: [undefined, { name: fieldError() }] })).toEqual(["keywordNote:note-y"]);
  });

  it("중첩 배열 항목은 부모 인덱스와 무관하게 자기 id 하나로 키를 만든다", () => {
    const errors: FieldErrors<StoryFixture> = { startingSetups: [undefined, { stats: [undefined, { name: fieldError() }] }] };
    expect(storyKeys(errors)).toEqual(["stat:stat-b2"]);
  });

  it("시작설정 아래 스탯·엔딩 오류는 시작설정 카드를 열지 않는다", () => {
    const errors: FieldErrors<StoryFixture> = {
      startingSetups: [{ stats: [{ min: fieldError() }], endings: [{ name: fieldError() }] }],
    };
    expect(storyKeys(errors)).toEqual(["ending:ending-a1", "stat:stat-a1"]);
  });

  it("시작설정 자기 필드 오류는 시작설정 키만 내고 스탯·엔딩 키는 내지 않는다", () => {
    expect(storyKeys({ startingSetups: [undefined, { name: fieldError() }] })).toEqual(["startingSetup:setup-b"]);
  });

  it("배열 자체 오류(.root 와 배열 노드의 message)는 키를 내지 않는다", () => {
    const errors: FieldErrors<StoryFixture> = {
      keywordNotes: { root: fieldError("노트는 50개까지예요.") },
      shortcuts: fieldError("단축어를 확인해주세요."),
      startingSetups: [{ stats: { root: fieldError() } }],
      storySetting: { developmentExamples: { root: fieldError("전개 예시는 3개까지예요.") } },
    };
    expect(storyKeys(errors)).toEqual([]);
  });

  it("항목 노드 자체에 걸린 오류는 그 항목 키를 낸다", () => {
    expect(storyKeys({ shortcuts: [undefined, undefined, fieldError()] })).toEqual(["shortcut:short-z"]);
  });

  it("값 id 가 없는 목록은 인덱스 키를 낸다", () => {
    const errors: FieldErrors<StoryFixture> = { storySetting: { developmentExamples: [undefined, { userLine: fieldError() }] } };
    expect(storyKeys(errors)).toEqual(["developmentExample#1"]);
  });

  it("그룹 안 규칙 오류는 엔딩 키와 규칙 그룹 키를 함께 낸다", () => {
    const errors: FieldErrors<StoryFixture> = {
      startingSetups: [
        undefined,
        { endings: [{ statRules: [undefined, { rules: [{ value: fieldError() }] }] }] },
      ],
    };
    expect(storyKeys(errors)).toEqual(["ending:ending-b1", "ruleGroup:group-b2"]);
  });

  it("한 항목에 오류가 여럿이어도 키는 하나다", () => {
    const errors: FieldErrors<StoryFixture> = { keywordNotes: [{ name: fieldError(), content: fieldError(), scope: fieldError() }] };
    expect(storyKeys(errors)).toEqual(["keywordNote:note-x"]);
  });

  it("값에 그 항목이 없거나 id 가 문자열이 아니면 키를 내지 않는다", () => {
    const values: StoryFixture = { ...STORY_VALUES, shortcuts: [{ id: 7 }] };
    const errors: FieldErrors<StoryFixture> = { shortcuts: [{ name: fieldError() }, { name: fieldError() }] };
    expect([...errorItemKeys(errors, values, STORY_LISTS, STORY_TABS)]).toEqual([]);
  });

  it("캐릭터 빌더 목록 정의로도 같은 규칙이 돈다", () => {
    const values: CharacterFixture = {
      intro: { exampleDialogues: [{ id: "dialogue-q" }] },
      situationalImages: [{ id: "image-p" }, { id: "image-q" }],
    };
    const errors: FieldErrors<CharacterFixture> = {
      intro: { exampleDialogues: [{ userLine: fieldError() }] },
      situationalImages: [undefined, { situationDescription: fieldError() }],
    };
    expect([...errorItemKeys(errors, values, CHARACTER_LISTS, CHARACTER_TABS)].sort()).toEqual([
      "exampleDialogue:dialogue-q",
      "situationalImage:image-q",
    ]);
  });
});
