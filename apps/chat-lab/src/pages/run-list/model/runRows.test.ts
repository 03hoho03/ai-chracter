import { describe, expect, it } from "vitest";

import type { RunListItem } from "@/shared/api/client";

import { rowsInFolder, summarizeGroup } from "./runRows";

function item(overrides: Partial<RunListItem> & Pick<RunListItem, "path">): RunListItem {
  return {
    runId: overrides.path,
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

const PROBES = "lm4/s3/probes";

describe("rowsInFolder", () => {
  it("뿌리에서는 대량 시도 폴더 밖 런을 한 줄씩, 대량 시도 폴더는 그룹 행 하나로 놓는다", () => {
    const rows = rowsInFolder(
      [
        item({ path: "guide/a/chat.jsonl", startedAt: "2026-10-01T10:00:00" }),
        item({ path: `${PROBES}/p1/a/chat.jsonl`, group: PROBES, startedAt: "2026-10-03T10:00:00" }),
        item({ path: `${PROBES}/p1/b/chat.jsonl`, group: PROBES, startedAt: "2026-10-02T10:00:00" }),
      ],
      "",
    );

    expect(rows.map((row) => [row.kind, row.key])).toEqual([
      ["group", `group:${PROBES}`],
      ["run", "guide/a/chat.jsonl"],
    ]);
  });

  it("대량 시도 폴더나 그 안을 고르면 런이 한 줄씩 놓인다", () => {
    const items = [
      item({ path: `${PROBES}/p1/a/chat.jsonl`, group: PROBES }),
      item({ path: `${PROBES}/p2/a/chat.jsonl`, group: PROBES }),
    ];

    expect(rowsInFolder(items, PROBES).map((row) => row.kind)).toEqual(["run", "run"]);
    expect(rowsInFolder(items, `${PROBES}/p1`).map((row) => row.key)).toEqual([`${PROBES}/p1/a/chat.jsonl`]);
  });

  it("고른 폴더 밖 런은 빠진다 — 이름 앞부분만 같은 옆 폴더도", () => {
    const rows = rowsInFolder([item({ path: "guide/a/chat.jsonl" }), item({ path: "guide-v2/a/chat.jsonl" })], "guide");

    expect(rows.map((row) => row.key)).toEqual(["guide/a/chat.jsonl"]);
  });

  it("최근 시작이 위, 시작 기록이 없는 런은 아래, 시각이 같으면 경로 순이다", () => {
    const rows = rowsInFolder(
      [
        item({ path: "c/chat.jsonl" }),
        item({ path: "b/chat.jsonl", startedAt: "2026-10-01T10:00:00+09:00" }),
        item({ path: "a/chat.jsonl", startedAt: "2026-10-01T10:00:00+09:00" }),
        item({ path: "d/chat.jsonl", startedAt: "2026-10-02T09:00:00+09:00" }),
      ],
      "",
    );

    expect(rows.map((row) => row.key)).toEqual(["d/chat.jsonl", "a/chat.jsonl", "b/chat.jsonl", "c/chat.jsonl"]);
  });

  it("시간대가 다른 시각도 실제 순서로 견준다", () => {
    const rows = rowsInFolder(
      [
        item({ path: "seoul/chat.jsonl", startedAt: "2026-10-01T10:00:00+09:00" }),
        item({ path: "utc/chat.jsonl", startedAt: "2026-10-01T02:00:00+00:00" }),
      ],
      "",
    );

    expect(rows.map((row) => row.key)).toEqual(["utc/chat.jsonl", "seoul/chat.jsonl"]);
  });

  it("그룹 행은 그 안에서 가장 최근 시작으로 다른 런과 견준다", () => {
    const rows = rowsInFolder(
      [
        item({ path: "solo/chat.jsonl", startedAt: "2026-10-02T10:00:00" }),
        item({ path: `${PROBES}/p1/a/chat.jsonl`, group: PROBES, startedAt: "2026-10-01T10:00:00" }),
        item({ path: `${PROBES}/p1/b/chat.jsonl`, group: PROBES, startedAt: "2026-10-03T10:00:00" }),
      ],
      "",
    );

    expect(rows.map((row) => row.kind)).toEqual(["group", "run"]);
  });
});

describe("summarizeGroup", () => {
  it("런 수·불일치 합·주의 합·원가 합과 시작 범위를 모은다", () => {
    const summary = summarizeGroup([
      item({ path: "a", mismatchCount: 2, cautionCount: 1, costUsd: 0.5, unpricedCalls: 0, startedAt: "2026-10-01T10:00:00" }),
      item({ path: "b", mismatchCount: 1, cautionCount: 0, costUsd: 0.25, unpricedCalls: 3, startedAt: "2026-10-03T10:00:00" }),
      item({ path: "c", mismatchCount: 0, cautionCount: 0, costUsd: null, startedAt: "2026-10-02T10:00:00" }),
      item({ path: "d", supported: false, format: "legacy" }),
      item({ path: "e", openError: "ValueError: 깨진 줄" }),
    ]);

    expect(summary).toEqual({
      runCount: 5,
      mismatchTotal: 3,
      cautionTotal: 1,
      pricedUsd: 0.75,
      unpricedCalls: 3,
      needsExportCount: 1,
      unopenedCount: 2,
      earliestStartedAt: "2026-10-01T10:00:00",
      latestStartedAt: "2026-10-03T10:00:00",
    });
  });
});
