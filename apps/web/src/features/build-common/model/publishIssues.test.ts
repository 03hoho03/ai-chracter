import { describe, expect, it } from "vitest";

import type { BuilderTab } from "@/entities/content";

import { flattenFieldErrorPaths } from "./fieldErrorPaths";
import {
  completedTabIds,
  errorsAtPaths,
  fieldLabelForPath,
  publishIssueRows,
  unchangedServerIssues,
  valueSnapshot,
  type FieldLabelTable,
} from "./publishIssues";

/** 스토리 빌더 탭 일부를 값 그대로 옮긴 픽스처 — build-common 은 build-story 를 import 하지 않는다. 겹치는 프리픽스
 * (`startingSetups` ↔ `startingSetups.*.stats`)가 검증 대상이다. */
const TABS: readonly BuilderTab[] = [
  { id: "profile", label: "프로필", fields: ["profile"], preview: "card" },
  { id: "startingSetup", label: "시작설정", fields: ["startingSetups"], preview: "chat" },
  { id: "stat", label: "스탯", fields: ["startingSetups.*.stats"], preview: "chat" },
  { id: "keywordNote", label: "키워드북", fields: ["keywordNotes"], preview: "chat" },
  { id: "mediaBook", label: "미디어 북", fields: ["mediaBook"], preview: "chat" },
];

const LABELS: FieldLabelTable = {
  "profile.name": { label: "이름" },
  startingSetups: { label: "시작설정" },
  "startingSetups.*.prologue": { label: "프롤로그" },
  "startingSetups.*.stats": { label: "스탯" },
  "startingSetups.*.stats.*.max": { label: "최대값" },
  "startingSetups.*.stats.*.rules": { label: "규칙" },
  keywordNotes: { label: "키워드북", item: "노트" },
  "keywordNotes.*.content": { label: "정보" },
  "mediaBook.cells": { label: "배치표", item: "칸" },
};

describe("fieldLabelForPath", () => {
  it("배열 위치마다 'N번째 항목'을 붙인다", () => {
    expect(fieldLabelForPath("startingSetups.0.prologue", LABELS)).toBe("1번째 시작설정 프롤로그");
    expect(fieldLabelForPath("startingSetups.1.stats.2.max", LABELS)).toBe("2번째 시작설정 3번째 스탯 최대값");
  });

  it("항목 이름이 목록 라벨과 다르면 항목 이름을 쓴다", () => {
    expect(fieldLabelForPath("keywordNotes.4.content", LABELS)).toBe("5번째 노트 정보");
    expect(fieldLabelForPath("mediaBook.cells.3", LABELS)).toBe("4번째 칸");
  });

  it("목록 자체의 오류는 목록 이름이다", () => {
    expect(fieldLabelForPath("keywordNotes", LABELS)).toBe("키워드북");
    expect(fieldLabelForPath("startingSetups", LABELS)).toBe("시작설정");
  });

  it("표에 없는 하위 칸은 가장 가까운 이름 있는 조상으로 부른다", () => {
    expect(fieldLabelForPath("startingSetups.0.stats.1.rules.2.id", LABELS)).toBe(
      "1번째 시작설정 2번째 스탯 3번째 규칙",
    );
    expect(fieldLabelForPath("mediaBook.cells.0.id", LABELS)).toBe("1번째 칸");
  });

  it("조상 어디에도 이름이 없으면 undefined", () => {
    expect(fieldLabelForPath("registration.genre", LABELS)).toBeUndefined();
  });
});

describe("publishIssueRows", () => {
  const labelFor = (path: string) => fieldLabelForPath(path, LABELS);

  it("'{탭} · {칸}' 이고, 칸 이름이 탭 이름으로 시작하면(순번 뒤 포함) 칸 이름만", () => {
    const rows = publishIssueRows(
      ["profile.name", "startingSetups.0.prologue", "startingSetups.0.stats.0.max", "keywordNotes"],
      TABS,
      labelFor,
    );
    expect(rows.map((row) => row.label)).toEqual([
      "프로필 · 이름",
      "1번째 시작설정 프롤로그",
      "스탯 · 1번째 시작설정 1번째 스탯 최대값",
      "키워드북",
    ]);
  });

  it("탭 이름이 낱말 일부로 시작하는 칸 이름에는 탭 이름을 그대로 붙인다", () => {
    const rows = publishIssueRows(["startingSetups.0.stats"], TABS, () => "스탯값 범위");
    expect(rows.map((row) => row.label)).toEqual(["스탯 · 스탯값 범위"]);
  });

  it("탭 순서로 줄을 세우고 같은 탭 안에서는 받은 순서를 지킨다", () => {
    const rows = publishIssueRows(
      ["keywordNotes.1.content", "startingSetups.0.stats.0.max", "keywordNotes.0.content", "profile.name"],
      TABS,
      labelFor,
    );
    expect(rows.map((row) => row.path)).toEqual([
      "profile.name",
      "startingSetups.0.stats.0.max",
      "keywordNotes.1.content",
      "keywordNotes.0.content",
    ]);
    expect(rows.map((row) => row.tabId)).toEqual(["profile", "stat", "keywordNote", "keywordNote"]);
  });

  it("같은 경로·같은 이름은 한 줄, 탭에 들지 않는 경로는 뺀다", () => {
    const rows = publishIssueRows(["profile.name", "profile.name", "unknown.path"], TABS, labelFor);
    expect(rows.map((row) => row.path)).toEqual(["profile.name"]);
    // 칸의 중복 id 오류와 그 칸 자체의 오류는 이름이 같아 먼저 온 경로 하나로 남는다.
    const cells = publishIssueRows(["mediaBook.cells.1.id", "mediaBook.cells.1"], TABS, labelFor);
    expect(cells.map((row) => [row.path, row.label])).toEqual([["mediaBook.cells.1.id", "미디어 북 · 2번째 칸"]]);
  });

  it("칸 이름을 못 찾으면 탭 이름만 남긴다", () => {
    const rows = publishIssueRows(["profile.oneLiner"], TABS, labelFor);
    expect(rows.map((row) => row.label)).toEqual(["프로필"]);
  });

  it("호출부가 준 이름(서버 키 라벨)을 칸 이름으로 쓴다", () => {
    const rows = publishIssueRows(["startingSetups.0.stats"], TABS, () => "스탯 범위(최소값 < 최대값)");
    expect(rows.map((row) => row.label)).toEqual(["스탯 범위(최소값 < 최대값)"]);
    expect(publishIssueRows(["startingSetups.0.stats"], TABS, () => "규칙이 없는 스탯").map((row) => row.label)).toEqual([
      "스탯 · 규칙이 없는 스탯",
    ]);
  });
});

describe("completedTabIds", () => {
  const required = new Set(["profile", "startingSetup", "keywordNote"]);

  it("오류가 하나도 없는 필수 탭만 남는다", () => {
    expect(completedTabIds(required, ["profile.name"], TABS)).toEqual(new Set(["startingSetup", "keywordNote"]));
  });

  it("하위 탭 오류는 그 하위 탭만 막는다 — 스탯 칸 오류가 시작설정 탭의 채움을 지우지 않는다", () => {
    expect(completedTabIds(required, ["startingSetups.0.stats.0.max"], TABS)).toEqual(required);
  });

  it("필수가 아닌 탭은 오류가 없어도 들지 않는다", () => {
    expect(completedTabIds(new Set(), [], TABS)).toEqual(new Set());
  });
});

describe("unchangedServerIssues", () => {
  const values = { keywordNotes: [{ content: "a" }], profile: { name: "도희" } };
  const issue = (path: string) => ({ path, message: "필수 항목이에요.", snapshot: valueSnapshot(values, path) });

  it("거절받은 뒤 값이 그대로인 거절만 남는다", () => {
    const issues = [issue("profile.name"), issue("keywordNotes")];
    const next = { ...values, profile: { name: "세빈" } };
    expect(unchangedServerIssues(issues, next).map((entry) => entry.path)).toEqual(["keywordNotes"]);
  });

  it("목록 자리 거절은 그 아래 무엇이 바뀌어도 풀린다", () => {
    const next = { ...values, keywordNotes: [{ content: "ab" }] };
    expect(unchangedServerIssues([issue("keywordNotes")], next)).toEqual([]);
  });

  it("값이 없던 자리도 비교할 수 있다", () => {
    const absent = issue("mediaBook");
    expect(unchangedServerIssues([absent], values)).toEqual([absent]);
  });
});

describe("errorsAtPaths", () => {
  it("경로 순서를 지켜 오류 객체로 세운다", () => {
    const paths = ["profile.name", "startingSetups.0.prologue", "startingSetups.1.name"];
    expect(flattenFieldErrorPaths(errorsAtPaths(paths))).toEqual(paths);
  });
});
