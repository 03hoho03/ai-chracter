import type { CharacterBuilderTab } from "./tabs";

/** 캐릭터 빌더의 접히는 반복 항목 목록 — 셸이 발행 실패 때 `errorItemKeys` 에 넘긴다. 객체 키가 열림 키의 목록
 * 이름이다(`itemOpenKey("exampleDialogue", id)`). */
export const CHARACTER_COLLAPSIBLE_LISTS = {
  exampleDialogue: { path: "intro.exampleDialogues", tabId: "intro", key: "id" },
  situationalImage: { path: "situationalImages", tabId: "advanced", key: "id" },
} as const satisfies Record<string, { path: string; tabId: CharacterBuilderTab; key: "id" | "index" }>;

export type CharacterCollapsibleList = keyof typeof CHARACTER_COLLAPSIBLE_LISTS;
