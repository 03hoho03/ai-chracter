import type { RunListItem } from "@/shared/api/client";

import { isOpened, type GroupSummary } from "./runRows";

const FORMAT_LABELS = {
  current: "현행",
  preMessageId: "이전",
  legacy: "지원 안 함",
} as const satisfies Record<RunListItem["format"], string>;

/** 원가는 소수 넷째 자리로 자리를 고정한다 — 세로로 줄 선 칸에서 `$0.0912` 와 `$2.4187` 의 소수점이 맞는다. */
const USD_FORMAT = new Intl.NumberFormat("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 });

const COUNT_FORMAT = new Intl.NumberFormat("en-US");

const STAMP_PATTERN = /^\d{4}-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/;
const DATE_PATTERN = /^\d{4}-(\d{2})-(\d{2})/;

/**
 * 원가 칸에 무엇을 적을지. `$0.0000` 과 "원가를 모름"이 같은 모양이 되지 않게 갈래를 나눈다.
 * - `none`: 열지 않은 런 — 원가를 말할 자리가 아니다.
 * - `needsExport`: 턴 기록 파일이 없어 원가를 낼 수 없다.
 * - `lowerBound`: 합에서 빠진 것(단가표에 없는 호출, 턴 기록이 없는 런, 열지 못한 런)이 있어 실제 원가는 이보다 크거나 같다.
 */
export type CostView =
  | { kind: "none" }
  | { kind: "needsExport" }
  | { kind: "exact"; usd: number }
  | { kind: "lowerBound"; usd: number; unpricedCalls: number; needsExportCount: number; unopenedCount: number };

export function formatLabel(format: RunListItem["format"]): string {
  return FORMAT_LABELS[format];
}

export function formatUsd(usd: number): string {
  return `$${USD_FORMAT.format(usd)}`;
}

export function formatCount(count: number): string {
  return COUNT_FORMAT.format(count);
}

export function describeRunCost(item: RunListItem): CostView {
  if (!isOpened(item)) return { kind: "none" };
  if (item.costUsd == null) return { kind: "needsExport" };
  const unpricedCalls = item.unpricedCalls ?? 0;
  if (unpricedCalls > 0) {
    return { kind: "lowerBound", usd: item.costUsd, unpricedCalls, needsExportCount: 0, unopenedCount: 0 };
  }
  return { kind: "exact", usd: item.costUsd };
}

export function describeGroupCost(summary: GroupSummary): CostView {
  if (summary.unopenedCount === summary.runCount) return { kind: "none" };
  if (summary.runCount - summary.unopenedCount - summary.needsExportCount === 0) return { kind: "needsExport" };
  if (summary.unpricedCalls > 0 || summary.needsExportCount > 0 || summary.unopenedCount > 0) {
    return {
      kind: "lowerBound",
      usd: summary.pricedUsd,
      unpricedCalls: summary.unpricedCalls,
      needsExportCount: summary.needsExportCount,
      unopenedCount: summary.unopenedCount,
    };
  }
  return { kind: "exact", usd: summary.pricedUsd };
}

/**
 * 기록에 적힌 시각을 `월-일 시:분` 으로. 시간대를 바꾸지 않고 적힌 글자를 그대로 잘라 쓴다 — 측정 기록의 시각은 그 측정을 돌린
 * 컴퓨터의 시각이라, 바꾸면 로그 파일과 화면의 시각이 어긋난다. 모양이 다르면 적힌 그대로 둔다.
 */
export function formatStartedAt(text: string | null | undefined): string | undefined {
  if (text == null) return undefined;
  const match = STAMP_PATTERN.exec(text);
  if (!match) return text;
  const [, month = "", day = "", hour = "", minute = ""] = match;
  return `${month}-${day} ${hour}:${minute}`;
}

/** 그룹 행의 시작 칸 — 다른 날이면 `10-26~10-28`, 같은 날이면 그 날 하나. */
export function formatDateRange(earliest: string | undefined, latest: string | undefined): string | undefined {
  const from = datePart(earliest);
  const to = datePart(latest);
  if (from === undefined || to === undefined) return from ?? to;
  return from === to ? from : `${from}~${to}`;
}

/**
 * 모델 칸에 적을 첫 모델과 나머지 개수. 방 스냅숏의 실제 생성 모델이 먼저고, 스냅숏이 없으면 덤프에 적힌 보낸 모델을 쓴다.
 * 둘 다 없으면 undefined.
 */
export function summarizeModels(item: RunListItem): { first: string; extraCount: number } | undefined {
  const effective = item.effectiveChatModels ?? [];
  const models = effective.length > 0 ? effective : (item.generationModels ?? []);
  const [first] = models;
  return first === undefined ? undefined : { first, extraCount: models.length - 1 };
}

/** 하한 원가 옆에 붙일 까닭 — 무엇이 합에서 빠졌는가. */
export function lowerBoundNote(cost: Extract<CostView, { kind: "lowerBound" }>): string {
  // 조사는 마지막 낱말을 따른다 — 호출만 빠졌으면 "건이", 런이 빠졌으면 "개가".
  const missing = [
    cost.unpricedCalls > 0 ? `단가표에 없는 호출 ${formatCount(cost.unpricedCalls)}건` : undefined,
    cost.needsExportCount > 0 ? `턴 기록 파일이 없는 런 ${formatCount(cost.needsExportCount)}개` : undefined,
    cost.unopenedCount > 0 ? `열지 못한 런 ${formatCount(cost.unopenedCount)}개` : undefined,
  ].filter((part) => part !== undefined);
  const particle = cost.needsExportCount > 0 || cost.unopenedCount > 0 ? "가" : "이";
  return `${missing.join(", ")}${particle} 빠진 합이다`;
}

/** 측정 서버가 런 루트를 훑은 시각(UTC ISO)을 이 컴퓨터의 시각 `월-일 시:분:초` 로. */
export function formatClock(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function datePart(text: string | undefined): string | undefined {
  const match = text === undefined ? null : DATE_PATTERN.exec(text);
  if (!match) return undefined;
  const [, month = "", day = ""] = match;
  return `${month}-${day}`;
}
