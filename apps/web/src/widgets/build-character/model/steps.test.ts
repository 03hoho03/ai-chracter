import { describe, expect, it } from "vitest";

import { CHARACTER_FIELD_LABELS, CHARACTER_TABS } from "@/features/build-character";
import { errorsAtPaths, fieldLabelForPath, firstErrorLocation, publishIssueRows, tabsOfStep } from "@/features/build-common";

import { CHARACTER_TAB_STEPS, CHARACTER_TABS_IN_STEP_ORDER } from "./steps";

describe("캐릭터 묶음", () => {
  it("기본 설정은 프로필·프롬프트·상황별 이미지, 시작 장면은 인트로, 공개 준비는 등록이다", () => {
    expect(tabsOfStep(CHARACTER_TABS, CHARACTER_TAB_STEPS, "basics").map((tab) => tab.id)).toEqual([
      "profile",
      "prompt",
      "advanced",
    ]);
    expect(tabsOfStep(CHARACTER_TABS, CHARACTER_TAB_STEPS, "opening").map((tab) => tab.id)).toEqual(["intro"]);
    expect(tabsOfStep(CHARACTER_TABS, CHARACTER_TAB_STEPS, "publish").map((tab) => tab.id)).toEqual(["detail"]);
  });

  // 탭 배열은 인트로가 둘째지만, 확인 목록과 첫 오류 이동은 묶음 순서를 따라야 한다.
  it("묶음 순 탭 목록은 프로필·프롬프트·상황별 이미지·인트로·등록이다", () => {
    expect(CHARACTER_TABS_IN_STEP_ORDER.map((tab) => tab.id)).toEqual(["profile", "prompt", "advanced", "intro", "detail"]);
  });

  it("발행 전 확인 목록과 첫 오류 이동은 프롬프트를 인트로보다 먼저 둔다", () => {
    const paths = ["intro.firstMessage", "prompt.characterPrompt"];
    const rows = publishIssueRows(paths, CHARACTER_TABS_IN_STEP_ORDER, (path) => fieldLabelForPath(path, CHARACTER_FIELD_LABELS));
    expect(rows.map((row) => row.tabId)).toEqual(["prompt", "intro"]);
    expect(firstErrorLocation(errorsAtPaths(paths), CHARACTER_TABS_IN_STEP_ORDER)?.tabId).toBe("prompt");
  });
});
