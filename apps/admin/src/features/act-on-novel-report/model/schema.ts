import { z } from "zod";

import type { NovelReportAction } from "@/entities/report";

export type NovelReportProcessAction = NovelReportAction["action"];

export const NOVEL_REPORT_ACTION_LABELS: Record<NovelReportProcessAction, string> = {
  restrict: "노벨 이용제한",
  reject: "조치 없음(반려)",
};

export const novelReportActionSchema = z.object({
  action: z.enum(["restrict", "reject"], { message: "처리 방법을 선택해주세요." }),
  adminComment: z.string().trim().min(1, "조치 사유를 입력해주세요."),
});

export type NovelReportActionValues = z.infer<typeof novelReportActionSchema>;
