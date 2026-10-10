import { describe, expect, it } from "vitest";

import { CHARACTER_TABS } from "@/features/build-character";

import { CHARACTER_REQUIRED_TAB_IDS } from "./requiredTabs";

/** 탭 본문 파일을 글자로 읽는다 — 화면에 필수 별표(`RequiredText`)를 실제로 그리는 탭이 어디인지 보려는 것이다. */
const TAB_SOURCES = import.meta.glob<string>("../ui/*Tab.tsx", { query: "?raw", import: "default", eager: true });

/** `../ui/PromptTab.tsx` → `prompt`. 탭 본문 파일 이름은 탭 id 를 대문자로 시작해 `Tab` 을 붙인 것이다. */
function tabIdOfFile(filePath: string): string {
  const base = filePath.split("/").pop()?.replace(/Tab\.tsx$/, "") ?? "";
  return base.charAt(0).toLowerCase() + base.slice(1);
}

describe("CHARACTER_REQUIRED_TAB_IDS", () => {
  it("빈 초안에서 오류가 나는 탭은 프로필·인트로·프롬프트·등록이다", () => {
    expect([...CHARACTER_REQUIRED_TAB_IDS].sort()).toEqual(["detail", "intro", "profile", "prompt"]);
  });

  // 발행 검증에서 고른 탭과 칸 라벨에 별표를 그리는 탭이 같아야 탭의 별표와 칸의 별표가 서로 다른 말을 하지 않는다.
  it("칸 라벨에 필수 별표를 그리는 탭과 같다", () => {
    const tabIds = new Set<string>(CHARACTER_TABS.map((tab) => tab.id));
    const files = Object.entries(TAB_SOURCES).filter(([filePath]) => tabIds.has(tabIdOfFile(filePath)));
    // 탭마다 본문 파일이 하나씩 있어야 대조가 빈 것끼리의 비교가 되지 않는다.
    expect(files.map(([filePath]) => tabIdOfFile(filePath)).sort()).toEqual([...tabIds].sort());

    const tabsWithRequiredLabel = files
      .filter(([, source]) => source.includes("<RequiredText>"))
      .map(([filePath]) => tabIdOfFile(filePath));
    expect(tabsWithRequiredLabel.sort()).toEqual([...CHARACTER_REQUIRED_TAB_IDS].sort());
  });
});
