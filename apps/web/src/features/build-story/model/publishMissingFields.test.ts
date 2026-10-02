import { describe, expect, it } from "vitest";

import { STORY_MISSING_FIELD_FORM_PATH, STORY_MISSING_FIELD_LABELS } from "./publishMissingFields";
import { STORY_TABS } from "./tabs";

/** 폼 경로가 한 탭의 `fields` 프리픽스 아래에 드는지 — 첫 세그먼트 일치로 판정한다(errorTabs.ts 의 매칭과 같은 규칙).
 * 어느 탭에도 안 들면 setError 를 해도 탭 스트립에 오류 표시가 안 뜨고 이동할 탭도 없다. */
function tabIdsCovering(formPath: string): string[] {
  const head = formPath.split(".")[0];
  return STORY_TABS.filter((tab) => tab.fields.some((prefix) => prefix.split(".")[0] === head)).map((tab) => tab.id);
}

describe("STORY_MISSING_FIELD_FORM_PATH", () => {
  it("모든 폼 경로가 적어도 한 탭에 걸린다", () => {
    for (const formPath of Object.values(STORY_MISSING_FIELD_FORM_PATH)) {
      expect(tabIdsCovering(formPath ?? "")).not.toEqual([]);
    }
  });

  it("미디어 북 칸 수 초과는 미디어 북 탭으로 가고, 연결이 끊긴 칸은 라벨만 있고 가리킬 폼 경로가 없다", () => {
    const cellsPath = STORY_MISSING_FIELD_FORM_PATH["mediaBook.cells"];
    expect(tabIdsCovering(cellsPath ?? "")).toEqual(["mediaBook"]);
    expect(STORY_MISSING_FIELD_LABELS["mediaBook.cells"]).toBe("미디어 북 칸(50개 이하)");

    expect(STORY_MISSING_FIELD_LABELS["mediaBook.orphanCells"]).toBeTruthy();
    expect(STORY_MISSING_FIELD_FORM_PATH["mediaBook.orphanCells"]).toBeUndefined();
  });

  it("키워드북 두 키는 라벨이 있고 키워드북 탭으로 간다", () => {
    for (const key of ["keywordNotes.triggerKeywords", "keywordNotes.infoText"] as const) {
      expect(STORY_MISSING_FIELD_LABELS[key]).toMatch(/키워드북/);
      expect(tabIdsCovering(STORY_MISSING_FIELD_FORM_PATH[key] ?? "")).toEqual(["keywordNote"]);
    }
  });
});
