import { describe, expect, it } from "vitest";

import { storyBuilderSchema } from "./schema";
import { STORY_TABS } from "./tabs";

/** 한 탭의 `fields` 프리픽스가 최상위 키 `key`를 덮는지 — 첫 세그먼트 일치로 판정한다
 * (`errorTabs.ts`의 매칭과 같은 규칙). */
function tabsCovering(key: string): (typeof STORY_TABS)[number][] {
  return STORY_TABS.filter((tab) => tab.fields.some((prefix) => prefix.split(".")[0] === key));
}

describe("STORY_TABS", () => {
  it("startingSetups를 제외한 모든 스키마 최상위 키가 정확히 한 탭에 귀속된다", () => {
    const topLevelKeys = Object.keys(storyBuilderSchema.shape).filter((key) => key !== "startingSetups");

    for (const key of topLevelKeys) {
      expect(tabsCovering(key)).toHaveLength(1);
    }
  });

  it("startingSetups는 여러 탭이 공유하지만 적어도 한 탭이 그 경로를 덮는다", () => {
    expect(tabsCovering("startingSetups").length).toBeGreaterThanOrEqual(1);
  });

  it("startingSetups를 덮는 탭은 정확히 startingSetup/stat/situationNote/ending 넷이다", () => {
    const ids = tabsCovering("startingSetups")
      .map((tab) => tab.id)
      .sort();

    expect(ids).toEqual(["ending", "situationNote", "startingSetup", "stat"]);
  });

  // 상황 노트는 스탯 값으로 조건을 거는 목록이라 스탯 바로 뒤 탭이다.
  it("상황 노트 탭이 스탯 탭 바로 뒤에 온다", () => {
    const ids: string[] = STORY_TABS.map((tab) => tab.id);

    expect(ids.indexOf("situationNote")).toBe(ids.indexOf("stat") + 1);
  });
});
