import { CHARACTER_TABS, type CharacterBuilderTab } from "@/features/build-character";
import { tabsInStepOrder, type TabStepTable } from "@/features/build-common";

/**
 * 캐릭터 빌더 탭의 묶음. 인트로(첫 메시지·예시 대화·플레이가이드)는 대화가 시작되는 자리라 시작 장면이고, 프로필·프롬프트·상황별
 * 이미지는 기본 설정이다. 탭을 더하면 이 표가 타입 오류로 묶음을 요구한다.
 */
export const CHARACTER_TAB_STEPS = {
  profile: "basics",
  intro: "opening",
  prompt: "basics",
  advanced: "basics",
  detail: "publish",
} as const satisfies TabStepTable<CharacterBuilderTab>;

/** 첫 오류로 가는 이동과 발행 전 확인 목록이 쓰는 탭 순서 — 작가가 묶음 순서로 읽는 곳이다. 탭 줄과 `?tab=` 은 `CHARACTER_TABS` 그대로다. */
export const CHARACTER_TABS_IN_STEP_ORDER = tabsInStepOrder(CHARACTER_TABS, CHARACTER_TAB_STEPS);
