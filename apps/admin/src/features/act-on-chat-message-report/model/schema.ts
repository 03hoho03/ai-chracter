import { z } from "zod";

/** 처리는 상태를 바꾸는 것뿐이다 — 작품·댓글 신고 패널의 제재(이용제한·숨김)는 여기 없다.
 * 사유는 BE가 공백이면 422를 내므로 화면에서 먼저 막는다. */
export const chatMessageReportActionSchema = z.object({
  action: z.enum(["resolve", "reject"], { message: "처리 방법을 선택해주세요." }),
  adminComment: z.string().trim().min(1, "처리 사유를 입력해주세요."),
});

export type ChatMessageReportActionValues = z.infer<typeof chatMessageReportActionSchema>;
