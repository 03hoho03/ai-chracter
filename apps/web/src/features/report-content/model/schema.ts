import { z } from "zod";

import type { ReportReasonCategory } from "@/entities/content";

export const REPORT_REASON_OPTIONS: { value: ReportReasonCategory; label: string }[] = [
  { value: "adult", label: "성인/선정적 콘텐츠" },
  { value: "copyright", label: "저작권 침해" },
  { value: "hate", label: "혐오·범죄 조장" },
  { value: "spam", label: "스팸" },
  { value: "other", label: "기타" },
];

/** 화면이 실제로 그리는 목록을 스키마의 근거로 삼아 옵션과 검증이 어긋날 수 없게 한다. */
export const REPORT_REASON_VALUES = REPORT_REASON_OPTIONS.map((option) => option.value);

export const reportContentSchema = z.object({
  reason: z.enum(REPORT_REASON_VALUES, { message: "신고 사유를 선택해주세요" }),
});

export type ReportContentFormValues = z.infer<typeof reportContentSchema>;
