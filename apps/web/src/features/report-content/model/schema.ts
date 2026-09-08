import { z } from "zod";

import type { ReportReasonCategory } from "@/entities/content";

export const REPORT_REASON_LABELS: Record<ReportReasonCategory, string> = {
  adult: "성인/선정적 콘텐츠",
  copyright: "저작권 침해",
  hate: "혐오·범죄 조장",
  spam: "스팸",
  other: "기타",
};

export function isReportReason(value: string): value is ReportReasonCategory {
  return value in REPORT_REASON_LABELS;
}

/** 사유가 늘면 `REPORT_REASON_LABELS`(Record)가 컴파일 에러로 잡는다 — 목록·옵션을 손으로 또 적으면
 * 그 강제가 목록에는 걸리지 않아 새 사유가 신고 모달에서 조용히 빠진다(`entities/inquiry/model/
 * inquiryCategory.ts` 동형). 스키마도 같은 목록을 근거로 삼아 옵션과 검증이 어긋날 수 없다. */
export const REPORT_REASON_VALUES = Object.keys(REPORT_REASON_LABELS).filter(isReportReason);

export const REPORT_REASON_OPTIONS = REPORT_REASON_VALUES.map((value) => ({
  value,
  label: REPORT_REASON_LABELS[value],
}));

export const reportContentSchema = z.object({
  reason: z.enum(REPORT_REASON_VALUES, { message: "신고 사유를 선택해주세요" }),
});

export type ReportContentFormValues = z.infer<typeof reportContentSchema>;
