import type { RunListItem } from "@/shared/api/client";
import { runRecordGap } from "@/shared/api/recordGap";
import { formatCount } from "@/shared/lib/formatNumber";

import { isOpened, type GroupSummary } from "./runRows";

const FORMAT_LABELS = {
  current: "현행",
  preMessageId: "이전",
  legacy: "지원 안 함",
} as const satisfies Record<RunListItem["format"], string>;

const STAMP_PATTERN = /^\d{4}-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/;
const DATE_PATTERN = /^\d{4}-(\d{2})-(\d{2})/;

/**
 * 원가 칸에 무엇을 적을지. `$0.0000` 과 "원가를 모름"이 같은 모양이 되지 않게 갈래를 나눈다.
 * - `none`: 열지 않은 런 — 원가를 말할 자리가 아니다.
 * - `oldFormat`: `assistantMessageId` 이전 형식이라 턴 기록을 응답과 이을 수 없어 원가가 없다 — 내보내도 채워지지 않는다.
 * - `needsExport`: 턴 기록 파일이 없어 원가를 낼 수 없다.
 * - `lowerBound`: 합에서 빠진 것(단가표에 없는 호출, 입력 토큰이 기록되지 않은 호출, 턴 기록이 없는 런, 이전 형식 런, 열지 못한
 *   런)이 있어
 *   실제 원가는 이보다 크거나 같다. 런 하나가 하한인지는 측정 서버가 판정한 `costIsLowerBound` 를 따르고, 나머지 칸은 까닭 문구용이다.
 *   `hasTokenGap` 은 하한인데 단가 없는 호출로는 설명되지 않는 런이 있다는 것 — 측정 서버가 하한으로 보는 다른 까닭은 입력 토큰이
 *   기록되지 않은 호출뿐이다(목록 한 줄에는 그 호출 수가 없다).
 */
export type CostView =
  | { kind: "none" }
  | { kind: "oldFormat" }
  | { kind: "needsExport" }
  | { kind: "exact"; usd: number }
  | {
      kind: "lowerBound";
      usd: number;
      unpricedCalls: number;
      hasTokenGap: boolean;
      needsExportCount: number;
      oldFormatCount: number;
      unopenedCount: number;
    };

export function formatLabel(format: RunListItem["format"]): string {
  return FORMAT_LABELS[format];
}

export function describeRunCost(item: RunListItem): CostView {
  if (!isOpened(item)) return { kind: "none" };
  if (runRecordGap(item) === "oldFormat") return { kind: "oldFormat" };
  if (item.costUsd == null) return { kind: "needsExport" };
  if (item.costIsLowerBound !== true) return { kind: "exact", usd: item.costUsd };
  const unpricedCalls = item.unpricedCalls ?? 0;
  return {
    kind: "lowerBound",
    usd: item.costUsd,
    unpricedCalls,
    hasTokenGap: unpricedCalls === 0,
    needsExportCount: 0,
    oldFormatCount: 0,
    unopenedCount: 0,
  };
}

export function describeGroupCost(summary: GroupSummary): CostView {
  if (summary.unopenedCount === summary.runCount) return { kind: "none" };
  const pricedRunCount = summary.runCount - summary.unopenedCount - summary.needsExportCount - summary.oldFormatCount;
  // 원가가 있는 런이 없으면 합을 적지 않는다 — 내보내면 채워지는 런이 하나라도 있으면 그것을, 없으면 이전 형식이라 없다고 적는다.
  if (pricedRunCount === 0) return summary.needsExportCount > 0 ? { kind: "needsExport" } : { kind: "oldFormat" };
  if (
    summary.lowerBoundRunCount > 0 ||
    summary.needsExportCount > 0 ||
    summary.oldFormatCount > 0 ||
    summary.unopenedCount > 0
  ) {
    return {
      kind: "lowerBound",
      usd: summary.pricedUsd,
      unpricedCalls: summary.unpricedCalls,
      hasTokenGap: summary.tokenGapRunCount > 0,
      needsExportCount: summary.needsExportCount,
      oldFormatCount: summary.oldFormatCount,
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

/** 모델 칸의 값이 어느 기록에서 왔는가 — 실제로 보낸 값 둘(덤프·턴 기록)과 방 설정값. */
export type ModelSource = "dump" | "chatTurns" | "setting";

/** 모델 칸·미리보기에 붙이는 출처 이름. 설정값은 모델을 바꿔 돌린 런에서 실제로 보낸 모델과 다르다. */
export const MODEL_SOURCE_LABELS = {
  dump: "실제 보낸 값(덤프 생성 줄)",
  chatTurns: "실제 보낸 값(턴 기록의 생성 호출)",
  setting: "설정값(방 스냅숏 — 보낸 기록 없음)",
} as const satisfies Record<ModelSource, string>;

export type ModelSummary = { first: string; extraCount: number; source: ModelSource; title: string };

/**
 * 모델 칸에 적을 첫 모델과 나머지 개수, 그 출처. 측정 서버가 호출 기록에서 찾은 실제 보낸 모델이 먼저고, 그것이 비면 방 스냅숏의
 * 설정값을 쓰되 설정값이라고 적는다. 둘 다 없으면 undefined.
 */
export function summarizeModels(item: RunListItem): ModelSummary | undefined {
  const sent = item.sentChatModels ?? [];
  const from = item.sentChatModelsFrom;
  const [models, source]: [string[], ModelSource] =
    sent.length > 0 && from != null ? [sent, from] : [item.configuredChatModels ?? [], "setting"];
  const [first] = models;
  if (first === undefined) return undefined;
  return { first, extraCount: models.length - 1, source, title: `${MODEL_SOURCE_LABELS[source]}: ${models.join(", ")}` };
}

/** 하한 원가 옆에 붙일 까닭 — 무엇이 합에서 빠졌는가. */
export function lowerBoundNote(cost: Extract<CostView, { kind: "lowerBound" }>): string {
  // 조사는 마지막 낱말을 따른다 — 호출만 빠졌으면 "건이"·"몫이", 런이 빠졌으면 "개가".
  const missing = [
    cost.unpricedCalls > 0 ? `단가표에 없는 호출 ${formatCount(cost.unpricedCalls)}건` : undefined,
    cost.hasTokenGap ? "입력 토큰이 기록되지 않은 호출의 입력 몫" : undefined,
    cost.needsExportCount > 0 ? `턴 기록 파일이 없는 런 ${formatCount(cost.needsExportCount)}개` : undefined,
    cost.oldFormatCount > 0 ? `이전 형식이라 원가가 없는 런 ${formatCount(cost.oldFormatCount)}개` : undefined,
    cost.unopenedCount > 0 ? `열지 못한 런 ${formatCount(cost.unopenedCount)}개` : undefined,
  ].filter((part) => part !== undefined);
  const particle = cost.needsExportCount > 0 || cost.oldFormatCount > 0 || cost.unopenedCount > 0 ? "가" : "이";
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
