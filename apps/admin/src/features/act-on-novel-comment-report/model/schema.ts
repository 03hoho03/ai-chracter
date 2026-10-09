import { z } from "zod";

import type { NovelCommentReportAction } from "@/entities/report";

export type NovelCommentReportProcessAction = NovelCommentReportAction["action"];

export const NOVEL_COMMENT_REPORT_ACTION_LABELS: Record<NovelCommentReportProcessAction, string> = {
  hide: "댓글 운영 숨김",
  reject: "조치 없음(반려)",
  delete: "댓글 삭제",
};

export const novelCommentReportActionSchema = z.object({
  action: z.enum(["hide", "delete", "reject"], { message: "처리 방법을 선택해주세요." }),
  adminComment: z.string().trim().min(1, "조치 사유를 입력해주세요."),
});

export type NovelCommentReportActionValues = z.infer<typeof novelCommentReportActionSchema>;
