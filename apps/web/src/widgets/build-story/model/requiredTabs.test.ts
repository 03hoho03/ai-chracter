import { describe, expect, it } from "vitest";

import { matchTabForPath } from "@/features/build-common";
import { STORY_FIELD_LABELS, STORY_TABS } from "@/features/build-story";

import { STORY_REQUIRED_TAB_IDS } from "./requiredTabs";

/**
 * 칸 라벨 표가 말하는 "언제나 필수인 탭". 필수 칸이면서 그 칸을 품은 목록(경로의 `*` 앞까지)도 모두 필수인 칸만 고른다 —
 * `startingSetups.*.stats.*.name` 은 스탯 목록이 필수가 아니라서 스탯을 만들 때만 필수다. 화면 칸이 아닌 조각(`$`)은 뺀다.
 */
function requiredTabsByLabels(): string[] {
  const labels: Record<string, { required: boolean | "conditional" }> = STORY_FIELD_LABELS;
  const result = new Set<string>();
  for (const [key, { required }] of Object.entries(labels)) {
    if (required !== true || key.includes("$")) continue;
    const segments = key.split(".");
    const listKeys = segments.flatMap((segment, index) => (segment === "*" ? [segments.slice(0, index).join(".")] : []));
    if (!listKeys.every((listKey) => labels[listKey]?.required === true)) continue;
    const tabId = matchTabForPath(key, STORY_TABS);
    if (tabId !== undefined) result.add(tabId);
  }
  return [...result].sort();
}

describe("STORY_REQUIRED_TAB_IDS", () => {
  it("빈 초안에서 오류가 나는 탭은 프로필·설정·시작설정·등록이다", () => {
    expect([...STORY_REQUIRED_TAB_IDS].sort()).toEqual(["profile", "registration", "setting", "startingSetup"]);
  });

  // 발행 검증에서 고른 탭과 칸 라벨 표(칸마다 별표를 그리는 소스)에서 고른 탭이 같아야 탭의 별표와 칸의 별표가 서로 다른 말을
  // 하지 않는다.
  it("칸 라벨 표에서 고른 언제나 필수인 탭과 같다", () => {
    expect([...STORY_REQUIRED_TAB_IDS].sort()).toEqual(requiredTabsByLabels());
  });
});
