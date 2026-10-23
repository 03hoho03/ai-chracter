import { z } from "zod";

import type { NovelReportAction } from "@/entities/report";

export type NovelReportProcessAction = NovelReportAction["action"];

export const NOVEL_REPORT_ACTION_LABELS: Record<NovelReportProcessAction, string> = {
  restrict: "노벨 이용제한",
  stop_sales: "노벨 판매 중단",
  reject: "조치 없음(반려)",
  illustration_takedown: "삽화 내림으로 처리 완료",
};

/** 판매 중단은 정책 스위치가 켜져 있을 때만 선택지에 보인다(패널이 가른다) — 스키마는 서버가 받는 셋을 다 받는다. */
export const novelReportActionSchema = z.object({
  action: z.enum(["stop_sales", "restrict", "reject"], { message: "처리 방법을 선택해주세요." }),
  adminComment: z.string().trim().min(1, "조치 사유를 입력해주세요."),
});

export type NovelReportActionValues = z.infer<typeof novelReportActionSchema>;
