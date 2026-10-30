import { describe, expect, it } from "vitest";

import type { RunListItem } from "@/shared/api/client";

import {
  describeGroupCost,
  describeRunCost,
  formatDateRange,
  formatLabel,
  formatStartedAt,
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
    lowerBoundRunCount: 0,
    tokenGapRunCount: 0,
    needsExportCount: 0,
    oldFormatCount: 0,
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

describe("describeRunCost", () => {
  it("턴 기록 파일이 없어 원가가 비면 내보내기 필요", () => {
    expect(describeRunCost(item({ costUsd: null, hasChatTurns: false }))).toEqual({ kind: "needsExport" });
  });

  it("측정 서버가 하한으로 보지 않은 원가는 그대로", () => {
    expect(describeRunCost(item({ costUsd: 0.25, unpricedCalls: 0, costIsLowerBound: false }))).toEqual({
      kind: "exact",
      usd: 0.25,
    });
  });

  it("단가표에 없는 호출이 빠졌으면 하한 — 빠진 호출 수는 까닭 문구에 쓴다", () => {
    expect(describeRunCost(item({ costUsd: 0.25, unpricedCalls: 2, costIsLowerBound: true }))).toEqual({
      kind: "lowerBound",
      usd: 0.25,
      unpricedCalls: 2,
      hasTokenGap: false,
      needsExportCount: 0,
      oldFormatCount: 0,
      unopenedCount: 0,
    });
  });

  it("단가 없는 호출이 없어도 측정 서버가 하한으로 보면 하한 — 입력 토큰이 기록되지 않은 호출이 섞인 런", () => {
    expect(describeRunCost(item({ costUsd: 0.25, unpricedCalls: 0, costIsLowerBound: true }))).toEqual({
      kind: "lowerBound",
      usd: 0.25,
      unpricedCalls: 0,
      hasTokenGap: true,
      needsExportCount: 0,
      oldFormatCount: 0,
      unopenedCount: 0,
    });
  });

  it("하한 여부는 단가 없는 호출 수로 다시 셈하지 않는다 — 측정 서버가 하한이 아니라고 하면 그대로", () => {
    expect(describeRunCost(item({ costUsd: 0.25, unpricedCalls: 2, costIsLowerBound: false }))).toEqual({
      kind: "exact",
      usd: 0.25,
    });
  });

  it("이전 형식은 턴 기록 파일이 있어도 없어도 원가 없음 — 내보내기 필요라고 하지 않는다", () => {
    expect(describeRunCost(item({ format: "preMessageId", costUsd: null, hasChatTurns: true }))).toEqual({ kind: "oldFormat" });
    expect(describeRunCost(item({ format: "preMessageId", costUsd: null, hasChatTurns: false }))).toEqual({ kind: "oldFormat" });
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
      hasTokenGap: false,
      needsExportCount: 1,
      oldFormatCount: 0,
      unopenedCount: 0,
    });
  });

  it("열지 못한 런이 섞여도 하한 — 그 런의 원가는 합에 없다", () => {
    expect(describeGroupCost(group({ runCount: 3, pricedUsd: 1.5, unopenedCount: 1 }))).toEqual({
      kind: "lowerBound",
      usd: 1.5,
      unpricedCalls: 0,
      hasTokenGap: false,
      needsExportCount: 0,
      oldFormatCount: 0,
      unopenedCount: 1,
    });
  });

  it("원가가 하한인 런이 섞이면 하한 — 단가 없는 호출 없이 토큰만 빠진 런이 있으면 그 까닭도 싣는다", () => {
    expect(
      describeGroupCost(group({ pricedUsd: 1.5, unpricedCalls: 2, lowerBoundRunCount: 2, tokenGapRunCount: 1 })),
    ).toEqual({
      kind: "lowerBound",
      usd: 1.5,
      unpricedCalls: 2,
      hasTokenGap: true,
      needsExportCount: 0,
      oldFormatCount: 0,
      unopenedCount: 0,
    });
  });

  it("하한인 런이 모두 단가 없는 호출로 설명되면 토큰 까닭은 싣지 않는다", () => {
    expect(
      describeGroupCost(group({ pricedUsd: 1.5, unpricedCalls: 2, lowerBoundRunCount: 1, tokenGapRunCount: 0 })),
    ).toMatchObject({ kind: "lowerBound", unpricedCalls: 2, hasTokenGap: false });
  });

  it("하한 여부는 단가 없는 호출 합이 아니라 하한인 런 수로 본다", () => {
    expect(describeGroupCost(group({ pricedUsd: 1.5, unpricedCalls: 2 }))).toEqual({ kind: "exact", usd: 1.5 });
    expect(describeGroupCost(group({ pricedUsd: 1.5, lowerBoundRunCount: 1, tokenGapRunCount: 1 }))).toMatchObject({
      kind: "lowerBound",
    });
  });

  it("빠진 것이 없으면 합 그대로", () => {
    expect(describeGroupCost(group({ pricedUsd: 1.5 }))).toEqual({ kind: "exact", usd: 1.5 });
  });

  it("이전 형식 런이 섞이면 하한이고 그 수를 싣는다 — 원가가 있는 런이 없으면 내보낼 런이 있을 때만 내보내기 필요", () => {
    expect(describeGroupCost(group({ pricedUsd: 1.5, oldFormatCount: 1 }))).toEqual({
      kind: "lowerBound",
      usd: 1.5,
      unpricedCalls: 0,
      hasTokenGap: false,
      needsExportCount: 0,
      oldFormatCount: 1,
      unopenedCount: 0,
    });
    expect(describeGroupCost(group({ oldFormatCount: 2 }))).toEqual({ kind: "oldFormat" });
    expect(describeGroupCost(group({ oldFormatCount: 1, needsExportCount: 1 }))).toEqual({ kind: "needsExport" });
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
  const base = {
    kind: "lowerBound",
    usd: 1,
    unpricedCalls: 0,
    hasTokenGap: false,
    needsExportCount: 0,
    oldFormatCount: 0,
    unopenedCount: 0,
  } as const;

  it("합에서 빠진 것을 문장으로", () => {
    expect(lowerBoundNote({ ...base, unpricedCalls: 2 })).toBe("단가표에 없는 호출 2건이 빠진 합이다");
    expect(lowerBoundNote({ ...base, unpricedCalls: 2, needsExportCount: 3 })).toBe(
      "단가표에 없는 호출 2건, 턴 기록 파일이 없는 런 3개가 빠진 합이다",
    );
    expect(lowerBoundNote({ ...base, unopenedCount: 4 })).toBe("열지 못한 런 4개가 빠진 합이다");
    expect(lowerBoundNote({ ...base, oldFormatCount: 2 })).toBe("이전 형식이라 원가가 없는 런 2개가 빠진 합이다");
  });

  it("입력 토큰이 기록되지 않은 호출은 수 없이 그 입력 몫이 빠졌다고 — 목록 한 줄에는 그 호출 수가 없다", () => {
    expect(lowerBoundNote({ ...base, hasTokenGap: true })).toBe("입력 토큰이 기록되지 않은 호출의 입력 몫이 빠진 합이다");
    expect(lowerBoundNote({ ...base, unpricedCalls: 1, hasTokenGap: true, unopenedCount: 2 })).toBe(
      "단가표에 없는 호출 1건, 입력 토큰이 기록되지 않은 호출의 입력 몫, 열지 못한 런 2개가 빠진 합이다",
    );
  });
});
