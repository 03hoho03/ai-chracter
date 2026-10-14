import { describe, expect, it } from "vitest";

import {
  createEmptyDraft,
  MAX_EXAMPLE_DIALOGUES,
  MAX_HASHTAGS,
  MAX_PLAY_GUIDE_LENGTH,
} from "@/entities/content";
import {
  CHARACTER_FIELD_LABELS,
  CHARACTER_MISSING_FIELDS,
  CHARACTER_TABS,
  characterBuilderSchema,
  characterMissingFieldFormPath,
  serverToForm,
} from "@/features/build-character";
import { fieldLabelForPath, matchTabForPath, publishIssueRows } from "@/features/build-common";

// 발행 전 확인 목록이 캐릭터 발행 검사의 모든 오류 경로에 칸 이름을 붙이는지 전수로 본다 — 셸과 같은 라벨 함수(칸 라벨 표에서
// 찾기)를 쓴다.

function validCharacter() {
  return {
    profile: { image: { assetId: "asset-1" }, name: "루나", oneLiner: "밤에만 문을 여는 사서" },
    intro: { firstMessage: "또 늦은 시간에 오셨네요.", exampleDialogues: [], playGuide: "" },
    prompt: { characterPrompt: "느리고 조용한 말투를 쓴다." },
    situationalImages: [],
    registration: {
      description: "밤의 도서관에서 만나는 사서",
      genre: "genre-romance",
      target: "all",
      hashtags: [],
      visibility: "public",
      novelPermission: "private",
    },
  };
}

function emptyCharacter() {
  const draft = createEmptyDraft("character");
  if (draft.type !== "character") throw new Error("캐릭터 빈 초안이 아니에요.");
  return serverToForm(draft);
}

const many = <T,>(count: number, make: (index: number) => T): T[] => Array.from({ length: count }, (_, i) => make(i));

const SCENARIOS: Record<string, unknown> = {
  "빈 초안": emptyCharacter(),
  "빈 예시 대화": {
    ...validCharacter(),
    intro: { ...validCharacter().intro, exampleDialogues: [{ id: "d1", userLine: "", characterLine: " " }] },
  },
  [`예시 대화 ${MAX_EXAMPLE_DIALOGUES + 1}개·플레이가이드 초과`]: {
    ...validCharacter(),
    intro: {
      ...validCharacter().intro,
      exampleDialogues: many(MAX_EXAMPLE_DIALOGUES + 1, (i) => ({ id: `d${i}`, userLine: "안녕", characterLine: "어서 와요" })),
      playGuide: "가".repeat(MAX_PLAY_GUIDE_LENGTH + 1),
    },
  },
  "상황별 이미지 빈 상황": {
    ...validCharacter(),
    situationalImages: [{ id: "i1", image: null, situationDescription: "" }],
  },
  "해시태그 초과": {
    ...validCharacter(),
    registration: { ...validCharacter().registration, hashtags: many(MAX_HASHTAGS + 1, (i) => `태그${i}`) },
  },
};

function issuePaths(value: unknown): string[] {
  const result = characterBuilderSchema.safeParse(value);
  return result.success ? [] : result.error.issues.map((issue) => issue.path.map(String).join("."));
}

const labelFor = (path: string) => fieldLabelForPath(path, CHARACTER_FIELD_LABELS);

describe("캐릭터 발행 전 확인 목록 라벨 전수", () => {
  it("기준 값은 오류가 없다(아래 시나리오의 오류가 넣은 위반에서만 나온다)", () => {
    expect(issuePaths(validCharacter())).toEqual([]);
  });

  it.each(Object.entries(SCENARIOS))("%s — 모든 오류 경로에 칸 이름과 탭이 있다", (_name, value) => {
    const paths = issuePaths(value);
    expect(paths.length).toBeGreaterThan(0);
    for (const path of paths) {
      expect({ path, label: labelFor(path), tab: matchTabForPath(path, CHARACTER_TABS) }).toEqual({
        path,
        label: expect.any(String),
        tab: expect.any(String),
      });
    }
    for (const row of publishIssueRows(paths, CHARACTER_TABS, labelFor)) expect(row.label).not.toMatch(/그 밖의/);
  });

  it("칸 이름은 탭 이름 뒤에 부모 항목 순번과 함께 붙고, 탭 이름으로 시작하면 탭 이름을 다시 붙이지 않는다", () => {
    const rows = publishIssueRows(
      ["intro.exampleDialogues.0.userLine", "situationalImages.1.situationDescription", "registration.hashtags"],
      CHARACTER_TABS,
      labelFor,
    );
    expect(rows.map((row) => row.label)).toEqual([
      "인트로 · 1번째 예시 대화 사용자 대사",
      "2번째 상황별 이미지 노출할 상황",
      "등록 · 해시태그",
    ]);
  });
});

describe("캐릭터 서버 400 키 라벨 전수", () => {
  it.each(CHARACTER_MISSING_FIELDS)("%s 는 칸에 걸리고 칸 라벨 표에 이름이 있다", (field) => {
    const path = characterMissingFieldFormPath(field) ?? "";
    expect(labelFor(path)).toEqual(expect.any(String));
    expect(publishIssueRows([path], CHARACTER_TABS, labelFor)).toHaveLength(1);
  });

  it("빌더가 모르는 키는 옮기지 않는다", () => {
    expect(characterMissingFieldFormPath("constructor")).toBeUndefined();
    expect(characterMissingFieldFormPath("futureField")).toBeUndefined();
  });
});
