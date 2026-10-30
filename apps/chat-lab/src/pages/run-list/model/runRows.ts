import type { RunListItem } from "@/shared/api/client";
import { compareText } from "@/shared/lib/compareText";

import { isWithinFolder } from "./folderTree";

/** 대량 시도 폴더 하나를 접은 그룹 행의 합. */
export type GroupSummary = {
  runCount: number;
  mismatchTotal: number;
  cautionTotal: number;
  /** 원가가 있는 런들의 합. 턴 기록이 없는 런·단가 없는 호출은 빠져 있다. */
  pricedUsd: number;
  unpricedCalls: number;
  /** 원가가 있는 런 가운데 측정 서버가 원가를 하한으로 본 런 수(단가 없는 호출이나 입력 토큰 없는 호출이 섞임). */
  lowerBoundRunCount: number;
  /** 그 가운데 단가 없는 호출이 없는 런 수 — 하한의 까닭이 입력 토큰이 기록되지 않은 호출뿐인 런이다. */
  tokenGapRunCount: number;
  /** 열었지만 턴 기록 파일이 없어 원가가 빈 런 수. */
  needsExportCount: number;
  /** 지원하지 않는 형식이거나 열다 실패한 런 수. */
  unopenedCount: number;
  earliestStartedAt?: string;
  latestStartedAt?: string;
};

/** 런 표의 한 행 — 런 하나, 또는 고른 폴더 밖에서 본 대량 시도 폴더 하나. */
export type RunRow =
  | { kind: "run"; key: string; item: RunListItem }
  | { kind: "group"; key: string; folder: string; summary: GroupSummary };

/** 측정 서버가 열어서 칸을 채운 런인가. 지원하지 않는 형식과 열다 실패한 런은 경로·형식 밖 칸이 비어 있다. */
export function isOpened(item: RunListItem): boolean {
  return item.supported && item.openError == null;
}

/**
 * 고른 폴더 아래 런을 표의 행으로. 대량 시도 폴더 밖에서 보면 그 폴더 안 런은 그룹 행 하나로 접고, 그 폴더나 그 안을 고르면 런을
 * 한 줄씩 놓는다 — 대량 시도 폴더 하나에 런이 천 개를 넘을 수 있어, 펼친 채로 두면 나머지 런이 표에서 묻힌다.
 *
 * 순서는 최근 시작이 위다. 시작 기록이 없는 런은 아래로, 시각이 같으면 경로 순. 그룹 행은 그 안에서 가장 최근 시작으로 견준다.
 */
export function rowsInFolder(items: ReadonlyArray<RunListItem>, folder: string): RunRow[] {
  const rows: RunRow[] = [];
  const grouped = new Map<string, RunListItem[]>();

  for (const item of items) {
    if (!isWithinFolder(item.path, folder)) continue;
    if (item.group !== null && !isWithinFolder(folder, item.group)) {
      const members = grouped.get(item.group) ?? [];
      members.push(item);
      grouped.set(item.group, members);
    } else {
      rows.push({ kind: "run", key: item.runId, item });
    }
  }
  for (const [group, members] of grouped) {
    rows.push({ kind: "group", key: `group:${group}`, folder: group, summary: summarizeGroup(members) });
  }
  return rows.sort(compareRows);
}

export function summarizeGroup(items: ReadonlyArray<RunListItem>): GroupSummary {
  const summary: GroupSummary = {
    runCount: items.length,
    mismatchTotal: 0,
    cautionTotal: 0,
    pricedUsd: 0,
    unpricedCalls: 0,
    lowerBoundRunCount: 0,
    tokenGapRunCount: 0,
    needsExportCount: 0,
    unopenedCount: 0,
  };
  let earliest: number | undefined;
  let latest: number | undefined;

  for (const item of items) {
    if (!isOpened(item)) {
      summary.unopenedCount += 1;
      continue;
    }
    summary.mismatchTotal += item.mismatchCount ?? 0;
    summary.cautionTotal += item.cautionCount ?? 0;
    if (item.costUsd == null) {
      summary.needsExportCount += 1;
    } else {
      summary.pricedUsd += item.costUsd;
      summary.unpricedCalls += item.unpricedCalls ?? 0;
      if (item.costIsLowerBound === true) {
        summary.lowerBoundRunCount += 1;
        if ((item.unpricedCalls ?? 0) === 0) summary.tokenGapRunCount += 1;
      }
    }
    const time = parseTime(item.startedAt);
    if (time === undefined || item.startedAt == null) continue;
    if (earliest === undefined || time < earliest) {
      earliest = time;
      summary.earliestStartedAt = item.startedAt;
    }
    if (latest === undefined || time > latest) {
      latest = time;
      summary.latestStartedAt = item.startedAt;
    }
  }
  return summary;
}

function compareRows(a: RunRow, b: RunRow): number {
  const timeA = sortTime(a);
  const timeB = sortTime(b);
  if (timeA !== timeB) {
    if (timeA === undefined) return 1;
    if (timeB === undefined) return -1;
    return timeB - timeA;
  }
  return compareText(sortPath(a), sortPath(b));
}

function sortTime(row: RunRow): number | undefined {
  return row.kind === "run" ? parseTime(row.item.startedAt) : parseTime(row.summary.latestStartedAt);
}

function sortPath(row: RunRow): string {
  return row.kind === "run" ? row.item.path : row.folder;
}

/** 기록의 ISO 시각을 견줄 수 있는 수로. 시간대가 적힌 시각은 그 시간대대로, 읽지 못하면 undefined. */
function parseTime(text: string | null | undefined): number | undefined {
  if (text == null) return undefined;
  const time = Date.parse(text);
  return Number.isNaN(time) ? undefined : time;
}
