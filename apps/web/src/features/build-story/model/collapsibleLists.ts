import type { StoryBuilderTab } from "./tabs";

/**
 * 스토리 빌더의 접히는 반복 항목 목록 — 셸이 발행 실패 때 `errorItemKeys` 에 넘긴다. 객체 키가 열림 키의 목록 이름이다
 * (`itemOpenKey("stat", stat.id)`). `path` 의 `*` 는 부모 배열 인덱스 자리, `key` 는 열림 키를 값 id 로 만들지(`id`)
 * 배열 위치로 만들지(`index`, 값 id 가 없는 전개 예시)다.
 *
 * 규칙 그룹 목록은 단일 규칙 오류에도 그 규칙 id 로 키를 내지만, 단일 규칙은 접는 머리 줄이 없어 그 키는 쓰이지 않는다.
 */
export const STORY_COLLAPSIBLE_LISTS = {
  developmentExample: { path: "storySetting.developmentExamples", tabId: "setting", key: "index" },
  startingSetup: { path: "startingSetups", tabId: "startingSetup", key: "id" },
  stat: { path: "startingSetups.*.stats", tabId: "stat", key: "id" },
  keywordNote: { path: "keywordNotes", tabId: "keywordNote", key: "id" },
  shortcut: { path: "shortcuts", tabId: "shortcut", key: "id" },
  ending: { path: "startingSetups.*.endings", tabId: "ending", key: "id" },
  ruleGroup: { path: "startingSetups.*.endings.*.statRules", tabId: "ending", key: "id" },
} as const satisfies Record<string, { path: string; tabId: StoryBuilderTab; key: "id" | "index" }>;

export type StoryCollapsibleList = keyof typeof STORY_COLLAPSIBLE_LISTS;

/** 미디어 북 인물·장면 섹션의 열림 키 목록 이름(`itemOpenKey(MEDIA_BOOK_AXIS_SECTION_LIST, "person")`). 섹션 단위로 접고
 * 폼 오류가 없어 위 목록에는 넣지 않는다. */
export const MEDIA_BOOK_AXIS_SECTION_LIST = "mediaBookAxis";

/** 스탯·엔딩 탭이 함께 보는 "고른 시작설정 id" 의 선택 이름(`useBuilderSelection`). */
export const SELECTED_STARTING_SETUP = "startingSetup";

/** 시작설정 하나에 매달린 탭 — 셸이 발행 실패 때 `errorParentItemId` 에 넘겨 그 탭들이 보여야 할 시작설정을 고른다. */
export const STARTING_SETUP_SCOPE = { path: "startingSetups", tabIds: ["stat", "ending"] } as const satisfies {
  path: string;
  tabIds: readonly StoryBuilderTab[];
};
