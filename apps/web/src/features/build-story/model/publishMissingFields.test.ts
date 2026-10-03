import { describe, expect, it } from "vitest";

import {
  collapseStartingSetupListPath,
  STORY_MISSING_FIELD_FORM_PATH,
  STORY_MISSING_FIELD_LABELS,
  STORY_STARTING_SETUP_LIST_LABELS,
} from "./publishMissingFields";
import { STORY_TABS } from "./tabs";

/** 폼 경로가 한 탭의 `fields` 프리픽스 아래에 드는지 — 첫 세그먼트 일치로 판정한다(errorTabs.ts 의 매칭과 같은 규칙).
 * 어느 탭에도 안 들면 setError 를 해도 탭 스트립에 오류 표시가 안 뜨고 이동할 탭도 없다. */
function tabIdsCovering(formPath: string): string[] {
  const head = formPath.split(".")[0];
  return STORY_TABS.filter((tab) => tab.fields.some((prefix) => prefix.split(".")[0] === head)).map((tab) => tab.id);
}

/** 폼 경로가 그 탭의 첫 `fields` 프리픽스(`startingSetups.*.stats` 꼴)와 세그먼트 단위로 맞는지 — 첫 세그먼트만 보면
 * 시작설정 아래 탭(시작설정·스탯·엔딩)이 셋 다 걸려, 실제로 어느 탭으로 가는지는 이렇게 가린다. */
function expectUnderTabPrefix(formPath: string, tabId: string) {
  const tab = STORY_TABS.find((candidate) => candidate.id === tabId);
  const [prefix] = tab?.fields ?? [];
  const prefixSegments = (prefix ?? "").split(".");
  const pathSegments = formPath.split(".");
  expect(pathSegments.length).toBe(prefixSegments.length);
  prefixSegments.forEach((segment, index) => {
    if (segment !== "*") expect(pathSegments[index]).toBe(segment);
  });
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

  it("스탯 범위가 어긋났다는 키는 라벨이 있고 스탯 탭으로 간다", () => {
    expect(STORY_MISSING_FIELD_LABELS["stats.range"]).toMatch(/스탯.*범위/);
    expectUnderTabPrefix(STORY_MISSING_FIELD_FORM_PATH["stats.range"] ?? "", "stat");
  });

  it("엔딩 조건이 지워진 스탯을 가리킨다는 키는 라벨이 있고 엔딩 탭 프리픽스 아래로 간다", () => {
    expect(STORY_MISSING_FIELD_LABELS["endings.statRules"]).toMatch(/엔딩.*스탯/);

    // 엔딩 탭 프리픽스(`startingSetups.*.endings`)와 세그먼트 단위로 맞아야 탭 이동이 엔딩 탭으로 간다.
    expectUnderTabPrefix(STORY_MISSING_FIELD_FORM_PATH["endings.statRules"] ?? "", "ending");
  });
});

describe("collapseStartingSetupListPath", () => {
  const labelByKey: Readonly<Record<string, string | undefined>> = STORY_STARTING_SETUP_LIST_LABELS;

  it("스탯·엔딩 칸의 오류 경로를 시작설정·항목 번호와 상관없이 라벨이 있는 키 하나로 접는다", () => {
    for (const path of ["startingSetups.0.stats.0.max", "startingSetups.3.stats.12.icon", "startingSetups.1.stats"]) {
      expect(labelByKey[collapseStartingSetupListPath(path)]).toBe("스탯");
    }
    for (const path of ["startingSetups.0.endings.2.name", "startingSetups.1.endings.0.statRules.1.value"]) {
      expect(labelByKey[collapseStartingSetupListPath(path)]).toBe("엔딩");
    }
  });

  it("스탯·엔딩이 아닌 경로는 그대로 둔다(이름이 비슷한 칸도)", () => {
    for (const path of ["startingSetups.0.name", "startingSetups", "startingSetups.0.statsNote", "registration.genre"]) {
      expect(collapseStartingSetupListPath(path)).toBe(path);
    }
  });

  it("접은 키는 그 목록을 맡은 탭의 오류 경로 프리픽스와 같다", () => {
    const prefixes = STORY_TABS.flatMap((tab) => tab.fields);
    for (const key of Object.keys(STORY_STARTING_SETUP_LIST_LABELS)) expect(prefixes).toContain(key);
  });
});
