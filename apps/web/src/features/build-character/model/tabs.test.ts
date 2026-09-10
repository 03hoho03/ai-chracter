import { describe, expect, it } from "vitest";

import { characterBuilderSchema } from "./schema";
import { CHARACTER_TABS } from "./tabs";

/** 한 탭의 `fields` 프리픽스가 최상위 키 `key`를 덮는지 — 첫 세그먼트 일치로 판정한다
 * (`errorTabs.ts`의 매칭과 같은 규칙, builder-techspec.md §4-1). */
function tabsCovering(key: string): (typeof CHARACTER_TABS)[number][] {
  return CHARACTER_TABS.filter((tab) => tab.fields.some((prefix) => prefix.split(".")[0] === key));
}

describe("CHARACTER_TABS", () => {
  it("모든 스키마 최상위 키가 정확히 한 탭에 귀속된다 (캐릭터는 탭 간 키 공유가 없다)", () => {
    const topLevelKeys = Object.keys(characterBuilderSchema.shape);

    for (const key of topLevelKeys) {
      expect(tabsCovering(key)).toHaveLength(1);
    }
  });

  it("registration은 탭 id가 다른 detail 탭에 귀속된다", () => {
    expect(tabsCovering("registration").map((tab) => tab.id)).toEqual(["detail"]);
  });
});
