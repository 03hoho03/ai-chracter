import { describe, expect, it } from "vitest";

import type { RunListItem } from "@/shared/api/client";

import {
  describeGroupCost,
  describeRunCost,
  formatDateRange,
  formatLabel,
  formatStartedAt,
  formatUsd,
  lowerBoundNote,
  summarizeModels,
} from "./runFormat";
import type { GroupSummary } from "./runRows";

function item(overrides: Partial<RunListItem> = {}): RunListItem {
  return {
    runId: "run",
    path: "a/chat.jsonl",
    group: null,
    format: "current",
    supported: true,
    roomId: "room",
    hasSnapshots: true,
    hasDump: true,
    hasChatTurns: true,
    ...overrides,
  };
}

function group(overrides: Partial<GroupSummary> = {}): GroupSummary {
  return {
    runCount: 2,
    mismatchTotal: 0,
    cautionTotal: 0,
    pricedUsd: 0,
    unpricedCalls: 0,
    needsExportCount: 0,
    unopenedCount: 0,
    ...overrides,
  };
}

describe("formatLabel", () => {
  it("형식마다 화면에 쓰는 이름", () => {
    expect(formatLabel("current")).toBe("현행");
    expect(formatLabel("preMessageId")).toBe("이전");
    expect(formatLabel("legacy")).toBe("지원 안 함");
  });
});

describe("formatUsd", () => {
  it("소수 넷째 자리까지, 천 단위 쉼표", () => {
    expect(formatUsd(0.0912)).toBe("$0.0912");
    expect(formatUsd(2.41874)).toBe("$2.4187");
    expect(formatUsd(1234.5)).toBe("$1,234.5000");
  });

  it("0 원도 같은 자릿수로 적는다 — 원가가 없는 것과는 다른 모양이다", () => {
    expect(formatUsd(0)).toBe("$0.0000");
  });
});

describe("describeRunCost", () => {
  it("턴 기록 파일이 없어 원가가 비면 내보내기 필요", () => {
    expect(describeRunCost(item({ costUsd: null, hasChatTurns: false }))).toEqual({ kind: "needsExport" });
  });

  it("단가 없는 호출이 없으면 원가 그대로", () => {
    expect(describeRunCost(item({ costUsd: 0.25, unpricedCalls: 0 }))).toEqual({ kind: "exact", usd: 0.25 });
  });

  it("단가표에 없는 호출이 빠졌으면 하한", () => {
    expect(describeRunCost(item({ costUsd: 0.25, unpricedCalls: 2 }))).toEqual({
      kind: "lowerBound",
      usd: 0.25,
      unpricedCalls: 2,
      needsExportCount: 0,
      unopenedCount: 0,
    });
  });

  it("열지 않은 런(지원 안 함·열 수 없음)은 원가를 말하지 않는다", () => {
    expect(describeRunCost(item({ supported: false, format: "legacy" }))).toEqual({ kind: "none" });
    expect(describeRunCost(item({ openError: "ValueError: 깨진 줄" }))).toEqual({ kind: "none" });
  });
});

describe("describeGroupCost", () => {
  it("원가가 있는 런이 하나도 없으면 내보내기 필요", () => {
    expect(describeGroupCost(group({ needsExportCount: 2 }))).toEqual({ kind: "needsExport" });
  });

  it("턴 기록이 없는 런이 섞이면 하한", () => {
    expect(describeGroupCost(group({ pricedUsd: 1.5, needsExportCount: 1 }))).toEqual({
      kind: "lowerBound",
      usd: 1.5,
      unpricedCalls: 0,
      needsExportCount: 1,
      unopenedCount: 0,
    });
  });

  it("열지 못한 런이 섞여도 하한 — 그 런의 원가는 합에 없다", () => {
    expect(describeGroupCost(group({ runCount: 3, pricedUsd: 1.5, unopenedCount: 1 }))).toEqual({
      kind: "lowerBound",
      usd: 1.5,
      unpricedCalls: 0,
      needsExportCount: 0,
      unopenedCount: 1,
    });
  });

  it("빠진 것이 없으면 합 그대로", () => {
    expect(describeGroupCost(group({ pricedUsd: 1.5 }))).toEqual({ kind: "exact", usd: 1.5 });
  });

  it("모든 런이 열리지 않았으면 말하지 않는다", () => {
    expect(describeGroupCost(group({ unopenedCount: 2 }))).toEqual({ kind: "none" });
  });
});

describe("formatStartedAt", () => {
  it("기록에 적힌 시각을 월-일 시:분으로 — 시간대를 바꾸지 않는다", () => {
    expect(formatStartedAt("2026-10-29T22:14:03.120+09:00")).toBe("10-29 22:14");
    expect(formatStartedAt("2026-10-29 22:14:03")).toBe("10-29 22:14");
  });

  it("모양이 다르면 적힌 그대로, 없으면 undefined", () => {
    expect(formatStartedAt("어제 밤")).toBe("어제 밤");
    expect(formatStartedAt(null)).toBeUndefined();
    expect(formatStartedAt(undefined)).toBeUndefined();
  });
});

describe("formatDateRange", () => {
  it("다른 날이면 날짜 범위, 같은 날이면 그 날 하나", () => {
    expect(formatDateRange("2026-10-26T09:00:00", "2026-10-28T21:15:00")).toBe("10-26~10-28");
    expect(formatDateRange("2026-10-26T09:00:00", "2026-10-26T21:15:00")).toBe("10-26");
  });

  it("시작 기록이 없으면 undefined", () => {
    expect(formatDateRange(undefined, undefined)).toBeUndefined();
  });
});

describe("summarizeModels", () => {
  it("실제 생성 모델의 첫째와 나머지 개수", () => {
    expect(summarizeModels(item({ effectiveChatModels: ["claude-opus-5-5", "gemini-3.5-flash-lite"] }))).toEqual({
      first: "claude-opus-5-5",
      extraCount: 1,
    });
  });

  it("방 스냅숏이 없어 실제 모델을 모르면 덤프의 보낸 모델로", () => {
    expect(summarizeModels(item({ effectiveChatModels: [], generationModels: ["claude-haiku-5-5"] }))).toEqual({
      first: "claude-haiku-5-5",
      extraCount: 0,
    });
  });

  it("둘 다 없으면 undefined", () => {
    expect(summarizeModels(item())).toBeUndefined();
  });
});

describe("lowerBoundNote", () => {
  it("합에서 빠진 것을 문장으로", () => {
    expect(lowerBoundNote({ kind: "lowerBound", usd: 1, unpricedCalls: 2, needsExportCount: 0, unopenedCount: 0 })).toBe(
      "단가표에 없는 호출 2건이 빠진 합이다",
    );
    expect(lowerBoundNote({ kind: "lowerBound", usd: 1, unpricedCalls: 2, needsExportCount: 3, unopenedCount: 0 })).toBe(
      "단가표에 없는 호출 2건, 턴 기록 파일이 없는 런 3개가 빠진 합이다",
    );
    expect(lowerBoundNote({ kind: "lowerBound", usd: 1, unpricedCalls: 0, needsExportCount: 0, unopenedCount: 4 })).toBe(
      "열지 못한 런 4개가 빠진 합이다",
    );
  });
});
