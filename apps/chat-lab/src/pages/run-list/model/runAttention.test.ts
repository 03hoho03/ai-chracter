import { describe, expect, it } from "vitest";

import type { RunListItem } from "@/shared/api/client";

import { describeAttention } from "./runAttention";

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
    costUsd: 0.1,
    unpricedCalls: 0,
    mismatchCount: 0,
    cautionCount: 0,
    ...overrides,
  };
}

describe("describeAttention", () => {
  it("불일치도 주의도 없으면 그 한 줄만", () => {
    expect(describeAttention(item())).toEqual([{ tone: "quiet", text: "불일치·주의 없음" }]);
  });

  it("열 수 없으면 그 까닭 하나만 — 다른 칸은 비어 있다", () => {
    const lines = describeAttention(item({ openError: "ValueError: 3번째 줄", costUsd: null, mismatchCount: null }));

    expect(lines).toEqual([{ tone: "danger", text: "열 수 없다 — ValueError: 3번째 줄" }]);
  });

  it("지원하지 않는 형식이면 열지 않는다는 한 줄", () => {
    const lines = describeAttention(item({ supported: false, format: "legacy", costUsd: null }));

    expect(lines).toHaveLength(1);
    expect(lines[0]?.tone).toBe("danger");
  });

  it("불일치·원가 빈칸·단가 없는 호출·주의를 그 순서로, 불일치와 주의는 따로 센다", () => {
    const lines = describeAttention(item({ mismatchCount: 3, cautionCount: 2, costUsd: 0.2, unpricedCalls: 1 }));

    expect(lines.map((line) => line.tone)).toEqual(["warn", "quiet", "warn"]);
    expect(lines[0]?.text).toContain("불일치 3건");
    expect(lines[1]?.text).toContain("1건");
    expect(lines[2]?.text).toContain("주의 2건");
  });

  it("턴 기록 파일이 없으면 원가가 빈 까닭을 말한다", () => {
    const lines = describeAttention(item({ costUsd: null, unpricedCalls: null, hasChatTurns: false }));

    expect(lines).toHaveLength(1);
    expect(lines[0]?.text).toContain("턴 기록 파일이 없어");
  });
});
