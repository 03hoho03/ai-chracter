import { describe, expect, it } from "vitest";

import {
  STORY_MISSING_FIELD_FORM_PATH,
  STORY_MISSING_FIELD_LABELS,
  storyMissingFieldFormPath,
  storyMissingFieldServerLabel,
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

  it("미디어 북 칸 수 초과와 연결이 끊긴 칸은 둘 다 라벨이 있고 미디어 북 탭으로 간다", () => {
    const cellsPath = STORY_MISSING_FIELD_FORM_PATH["mediaBook.cells"];
    expect(tabIdsCovering(cellsPath ?? "")).toEqual(["mediaBook"]);
    expect(STORY_MISSING_FIELD_LABELS["mediaBook.cells"]).toBe("미디어 북 칸(50개 이하)");

    // 화면에 그 칸이 없어 미디어 북 전체를 가리킨다 — 폼 경로가 없으면 칸에 걸리지 못해 발행 전 확인 목록에서 빠진다.
    expect(STORY_MISSING_FIELD_LABELS["mediaBook.orphanCells"]).toBeTruthy();
    expect(STORY_MISSING_FIELD_FORM_PATH["mediaBook.orphanCells"]).toBe("mediaBook");
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

  it("스탯 규칙의 세 키는 라벨이 있고 스탯 탭으로 간다", () => {
    expect(STORY_MISSING_FIELD_LABELS["stats.rules"]).toMatch(/규칙이 없는 스탯/);
    expect(STORY_MISSING_FIELD_LABELS["stats.ruleDelta"]).toMatch(/규칙.*범위 폭/);
    expect(STORY_MISSING_FIELD_LABELS["stats.rulesWithCounter"]).toMatch(/규칙.*턴당 자동 변화/);
    for (const key of ["stats.rules", "stats.ruleDelta", "stats.rulesWithCounter"] as const) {
      expectUnderTabPrefix(STORY_MISSING_FIELD_FORM_PATH[key] ?? "", "stat");
    }
  });

  it("엔딩 조건이 지워진 스탯을 가리킨다는 키는 라벨이 있고 엔딩 탭 프리픽스 아래로 간다", () => {
    expect(STORY_MISSING_FIELD_LABELS["endings.statRules"]).toMatch(/엔딩.*스탯/);
    // 서버는 지워진 우선순위 스탯도 이 키로 알린다 — 라벨이 조건만 말하면 작가가 우선순위 스탯 칸을 찾지 못한다.
    expect(STORY_MISSING_FIELD_LABELS["endings.statRules"]).toContain("우선순위 스탯");

    // 엔딩 탭 프리픽스(`startingSetups.*.endings`)와 세그먼트 단위로 맞아야 탭 이동이 엔딩 탭으로 간다.
    expectUnderTabPrefix(STORY_MISSING_FIELD_FORM_PATH["endings.statRules"] ?? "", "ending");
  });
});

describe("STORY_MISSING_FIELD_FORM_PATH — 상황 노트", () => {
  // 셋 다 서버가 어느 노트인지 알려 주지 않는다. 폼에서 그 노트를 못 찾을 때 이 경로가 상황 노트 탭으로 보낸다(시작설정 탭이 아니라).
  it("상황 노트 세 키는 라벨이 있고 상황 노트 탭 프리픽스 아래로 간다", () => {
    for (const key of [
      "situationNotes.emptyConditionRules",
      "situationNotes.infoText",
      "situationNotes.conditionRules",
    ] as const) {
      expect(STORY_MISSING_FIELD_LABELS[key]).toMatch(/상황 노트/);
      expectUnderTabPrefix(STORY_MISSING_FIELD_FORM_PATH[key] ?? "", "situationNote");
    }
  });
});

describe("storyMissingFieldFormPath", () => {
  it("비인덱스 키는 폼 경로 맵 그대로다", () => {
    for (const [field, formPath] of Object.entries(STORY_MISSING_FIELD_FORM_PATH)) {
      expect(storyMissingFieldFormPath(field)).toBe(formPath);
    }
  });

  it("서버가 인덱스를 박아 보내는 시작설정 이름·프롤로그와 엔딩 최소 턴을 그 칸의 폼 경로로 옮긴다", () => {
    expect(storyMissingFieldFormPath("startingSetups[0].name")).toBe("startingSetups.0.name");
    expect(storyMissingFieldFormPath("startingSetups[2].prologue")).toBe("startingSetups.2.prologue");
    expect(storyMissingFieldFormPath("startingSetups[1].endings[3].turnCountGate")).toBe(
      "startingSetups.1.endings.3.turnGate",
    );
  });

  it("빌더가 모르는 키는 옮기지 않는다", () => {
    expect(storyMissingFieldFormPath("startingSetups[0].openingSituation")).toBeUndefined();
    expect(storyMissingFieldFormPath("situationNotes.newRule")).toBeUndefined();
  });
});

describe("storyMissingFieldServerLabel", () => {
  it("칸 하나를 짚는 키는 서버 라벨을 주지 않아 칸 라벨 표가 이름을 정한다", () => {
    const fieldKeys = ["name", "oneLiner", "thumbnailAssetId", "customPrompt", "settingText", "startingSetups", "description"];
    for (const field of [...fieldKeys, "genreId", "target"]) {
      expect(storyMissingFieldServerLabel(field)).toBeUndefined();
    }
  });

  it("목록 자리만 가리키는 키는 무엇이 틀렸는지 말하는 서버 라벨을 준다", () => {
    expect(storyMissingFieldServerLabel("stats.range")).toBe(STORY_MISSING_FIELD_LABELS["stats.range"]);
    expect(storyMissingFieldServerLabel("keywordNotes.infoText")).toBe(STORY_MISSING_FIELD_LABELS["keywordNotes.infoText"]);
    expect(storyMissingFieldServerLabel("mediaBook.orphanCells")).toBe(STORY_MISSING_FIELD_LABELS["mediaBook.orphanCells"]);
  });

  it("인덱스 키와 모르는 키는 서버 라벨이 없다", () => {
    expect(storyMissingFieldServerLabel("startingSetups[1].prologue")).toBeUndefined();
    expect(storyMissingFieldServerLabel("constructor")).toBeUndefined();
  });
});
