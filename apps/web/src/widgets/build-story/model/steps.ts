import { tabsInStepOrder, type TabStepTable } from "@/features/build-common";
import { STORY_TABS, type StoryBuilderTab } from "@/features/build-story";

/**
 * 스토리 빌더 탭의 묶음. 시작 장면은 고른 시작설정 아래 목록을 고치는 네 탭(시작설정·스탯·상황 노트·엔딩)이고, 기본 설정은 작품 전체에
 * 걸리는 나머지 칸이다 — 미디어 북은 특정 시작설정에 속하지 않아 기본 설정에 둔다. 탭을 더하면 이 표가 타입 오류로 묶음을 요구한다.
 */
export const STORY_TAB_STEPS = {
  profile: "basics",
  setting: "basics",
  startingSetup: "opening",
  stat: "opening",
  situationNote: "opening",
  mediaBook: "basics",
  keywordNote: "basics",
  shortcut: "basics",
  ending: "opening",
  registration: "publish",
} as const satisfies TabStepTable<StoryBuilderTab>;

/** 첫 오류로 가는 이동과 발행 전 확인 목록이 쓰는 탭 순서 — 작가가 묶음 순서로 읽는 곳이다. 탭 줄과 `?tab=` 은 `STORY_TABS` 그대로다. */
export const STORY_TABS_IN_STEP_ORDER = tabsInStepOrder(STORY_TABS, STORY_TAB_STEPS);
