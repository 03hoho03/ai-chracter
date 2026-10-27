import { describe, expect, it } from "vitest";

import { errorsAtPaths, fieldLabelForPath, firstErrorLocation, publishIssueRows, tabsOfStep } from "@/features/build-common";
import { STORY_FIELD_LABELS, STORY_TABS } from "@/features/build-story";

import { STORY_TAB_STEPS, STORY_TABS_IN_STEP_ORDER } from "./steps";

const labelFor = (path: string) => fieldLabelForPath(path, STORY_FIELD_LABELS);

describe("스토리 묶음", () => {
  it("묶음 안 탭은 배열에서 걸러 낸 순서다", () => {
    expect(tabsOfStep(STORY_TABS, STORY_TAB_STEPS, "basics").map((tab) => tab.id)).toEqual([
      "profile",
      "setting",
      "mediaBook",
      "keywordNote",
      "shortcut",
    ]);
    expect(tabsOfStep(STORY_TABS, STORY_TAB_STEPS, "opening").map((tab) => tab.id)).toEqual([
      "startingSetup",
      "stat",
      "situationNote",
      "ending",
    ]);
    expect(tabsOfStep(STORY_TABS, STORY_TAB_STEPS, "publish").map((tab) => tab.id)).toEqual(["registration"]);
  });

  // 탭 배열(탭 줄·`?tab=`)과 다른 순서다. 확인 목록과 첫 오류 이동은 이 순서를 따라야 묶음 순서로 읽힌다.
  it("묶음 순 탭 목록은 기본 설정 다섯 → 시작 장면 넷 → 등록이다", () => {
    expect(STORY_TABS_IN_STEP_ORDER.map((tab) => tab.id)).toEqual([
      "profile",
      "setting",
      "mediaBook",
      "keywordNote",
      "shortcut",
      "startingSetup",
      "stat",
      "situationNote",
      "ending",
      "registration",
    ]);
  });

  it("발행 전 확인 목록은 기본 설정의 줄(미디어 북·키워드북)을 시작 장면의 줄보다 먼저 세운다", () => {
    const rows = publishIssueRows(
      ["startingSetups.0.prologue", "keywordNotes", "startingSetups.0.stats.1.max", "mediaBook.cells.3", "registration.description"],
      STORY_TABS_IN_STEP_ORDER,
      labelFor,
    );
    expect(rows.map((row) => row.tabId)).toEqual(["mediaBook", "keywordNote", "startingSetup", "stat", "registration"]);
  });

  it("첫 오류 이동은 시작설정보다 미디어 북으로 먼저 간다", () => {
    const errors = errorsAtPaths(["startingSetups.0.prologue", "mediaBook.cells.3"]);
    expect(firstErrorLocation(errors, STORY_TABS_IN_STEP_ORDER)?.tabId).toBe("mediaBook");
  });
});
