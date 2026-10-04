import { describe, expect, it } from "vitest";

import {
  MAX_SITUATION_NOTE_CONTENT_LENGTH,
  MAX_SITUATION_NOTE_NAME_LENGTH,
  MAX_SITUATION_NOTE_RULES,
  MAX_SITUATION_NOTES,
  SITUATION_NOTE_BLANK_CONTENT_MESSAGE,
  SITUATION_NOTE_EMPTY_CONDITIONS_MESSAGE,
  situationNoteSchema,
  startingSetupSchema,
  type RuleListItemValues,
  type SingleRuleValues,
  type SituationNoteValues,
} from "./schema";

// 상한 숫자는 서버(`StoryDraftPayload` 의 상황 노트 검사)와 같아야 한다. 폼이 더 느슨하면 자동저장이 서버 422 로 멈추고,
// 더 엄격하면 서버가 받는 노트를 작가가 못 만든다. 숫자를 상수와 따로 적어 두 쪽이 함께 바뀌었는지 여기서 본다.
describe("상황 노트 상한", () => {
  it("서버와 같은 숫자다 — 시작설정마다 노트 10, 이름 20자, 상황 800자, 조건 10개", () => {
    expect([MAX_SITUATION_NOTES, MAX_SITUATION_NOTE_NAME_LENGTH, MAX_SITUATION_NOTE_CONTENT_LENGTH, MAX_SITUATION_NOTE_RULES]).toEqual([
      10, 20, 800, 10,
    ]);
  });
});

function rule(id: string): SingleRuleValues {
  return { kind: "rule", id, statId: "s1", operator: "<=", value: 0, nextOp: null };
}

function note(overrides: Partial<SituationNoteValues> = {}): SituationNoteValues {
  return { id: "n1", name: "", content: "오늘은 상영회 당일이다.", conditionRules: [rule("r1")], ...overrides };
}

function issuesOf(value: SituationNoteValues): { path: PropertyKey[]; message: string }[] {
  const result = situationNoteSchema.safeParse(value);
  return result.success ? [] : result.error.issues.map((issue) => ({ path: issue.path, message: issue.message }));
}

describe("situationNoteSchema", () => {
  it("이름이 비어도 조건 하나와 상황이 있으면 통과한다", () => {
    expect(issuesOf(note())).toEqual([]);
  });

  // 조건 없는 노트는 서버가 저장은 받고 발행만 막는다. 발행 전 폼 검증이 같은 자리를 짚어야 작가가 그 노트로 간다.
  it("조건이 하나도 없으면 조건 칸에 오류를 건다", () => {
    expect(issuesOf(note({ conditionRules: [] }))).toEqual([
      { path: ["conditionRules"], message: SITUATION_NOTE_EMPTY_CONDITIONS_MESSAGE },
    ]);
  });

  // 서버는 그룹 자체를 조건으로 세지 않는다 — 빈 그룹만 있는 노트도 조건 0개로 발행이 막힌다.
  it("빈 그룹만 있는 노트도 조건이 없는 것으로 본다", () => {
    const emptyGroup: RuleListItemValues = { kind: "group", id: "g1", rules: [], nextOp: null };

    expect(issuesOf(note({ conditionRules: [emptyGroup] })).map((issue) => issue.path)).toEqual([["conditionRules"]]);
  });

  it("공백뿐인 상황은 상황 칸에 오류를 건다", () => {
    expect(issuesOf(note({ content: "  \n " }))).toEqual([
      { path: ["content"], message: SITUATION_NOTE_BLANK_CONTENT_MESSAGE },
    ]);
  });

  it("상황은 800자까지 받고 801자는 막는다", () => {
    expect(issuesOf(note({ content: "가".repeat(MAX_SITUATION_NOTE_CONTENT_LENGTH) }))).toEqual([]);
    expect(issuesOf(note({ content: "가".repeat(MAX_SITUATION_NOTE_CONTENT_LENGTH + 1) })).map((issue) => issue.path)).toEqual([
      ["content"],
    ]);
  });

  it("이름은 20자까지 받고 21자는 막는다", () => {
    expect(issuesOf(note({ name: "가".repeat(MAX_SITUATION_NOTE_NAME_LENGTH) }))).toEqual([]);
    expect(issuesOf(note({ name: "가".repeat(MAX_SITUATION_NOTE_NAME_LENGTH + 1) })).map((issue) => issue.path)).toEqual([
      ["name"],
    ]);
  });

  it("조건은 그룹 안 조건까지 세어 10개까지 받는다", () => {
    const ten: RuleListItemValues[] = [
      ...Array.from({ length: 7 }, (_, index) => rule(`r${index}`)),
      { kind: "group", id: "g1", nextOp: null, rules: [rule("g-a"), rule("g-b"), rule("g-c")] },
    ];
    const eleven: RuleListItemValues[] = [...ten, rule("r-extra")];

    expect(issuesOf(note({ conditionRules: ten }))).toEqual([]);
    expect(issuesOf(note({ conditionRules: eleven })).map((issue) => issue.path)).toEqual([["conditionRules"]]);
  });
});

describe("startingSetupSchema 의 상황 노트 목록", () => {
  function setupWith(count: number) {
    return {
      id: "s1",
      name: "가을 학기",
      prologue: "프롤로그",
      situationNotes: Array.from({ length: count }, (_, index) => note({ id: `n${index}` })),
    };
  }

  it("시작설정마다 노트 10개까지 받고 11개는 목록 자리에 오류를 건다", () => {
    expect(startingSetupSchema.safeParse(setupWith(MAX_SITUATION_NOTES)).success).toBe(true);

    const over = startingSetupSchema.safeParse(setupWith(MAX_SITUATION_NOTES + 1));
    expect(over.success ? [] : over.error.issues.map((issue) => issue.path)).toEqual([["situationNotes"]]);
  });

  it("노트를 적지 않은 시작설정은 빈 목록으로 읽는다", () => {
    const result = startingSetupSchema.safeParse({ id: "s1", name: "가을 학기", prologue: "프롤로그" });

    expect(result.success && result.data.situationNotes).toEqual([]);
  });
});
