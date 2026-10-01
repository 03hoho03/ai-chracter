import { z } from "zod";

import type { CommentReportReason } from "@/entities/comment";

export const REASON_OPTIONS: { [Reason in CommentReportReason]: { value: Reason; label: string } } = {
  adult: { value: "adult", label: "성인/선정적 콘텐츠" },
  copyright: { value: "copyright", label: "저작권 침해" },
  hate: { value: "hate", label: "혐오·범죄 조장" },
  spam: { value: "spam", label: "스팸" },
  other: { value: "other", label: "기타" },
};

export const commentReportReasonSchema = z.enum(Object.values(REASON_OPTIONS).map((option) => option.value), { message: "신고 사유를 선택해주세요." });
export const commentReportSchema = z.object({ reason: commentReportReasonSchema });
