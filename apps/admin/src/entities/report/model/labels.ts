import type { components } from "@ai-character-chat/api-types";

export type ReportReasonCategory = components["schemas"]["ReportReasonCategory"];

export const REPORT_REASON_LABELS: Record<ReportReasonCategory, string> = {
  adult: "성인물",
  copyright: "저작권 침해",
  hate: "혐오/차별",
  spam: "스팸",
  other: "기타",
};

export const REPORT_STATUS_LABELS: Record<components["schemas"]["ReportStatus"], string> = {
  pending: "대기중",
  resolved: "처리완료",
  rejected: "반려",
};

export function isReportReasonCategory(value: string): value is ReportReasonCategory {
  return value in REPORT_REASON_LABELS;
}

/** 사유가 늘면 `REPORT_REASON_LABELS`(Record)가 컴파일 에러로 잡는다 — 목록·옵션을 손으로 또 적으면
 * 그 강제가 목록에는 걸리지 않아 새 사유가 조용히 빠진다. 그래서 둘 다 키에서 도출한다. */
export const REPORT_REASON_VALUES = Object.keys(REPORT_REASON_LABELS).filter(isReportReasonCategory);

export const REPORT_REASON_OPTIONS = REPORT_REASON_VALUES.map((value) => ({
  value,
  label: REPORT_REASON_LABELS[value],
}));
