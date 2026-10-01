import { z } from "zod";

export const commentReportActionSchema = z.object({
  action: z.enum(["hide", "restore", "reject"]),
  adminComment: z.string().trim().min(1, "조치 사유를 입력해주세요."),
});
export type CommentReportActionValues = z.infer<typeof commentReportActionSchema>;
