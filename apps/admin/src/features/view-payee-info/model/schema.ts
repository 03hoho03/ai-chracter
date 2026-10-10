import { z } from "zod";

import { PAYEE_INFO_VIEW_REASON_CATEGORY_VALUES } from "@/entities/creator-payout";

/** 지급 정보 열람 전용 사유 분류를 쓴다(서버도 이 경로만의 enum 이다). 분류 필수, 사유 상세는 앞뒤 공백을 뺀 1~1,000자 — 서버도
 * 공백 사유를 422 로, 1,000자 초과를 거부한다. */
export const viewPayeeReasonSchema = z
  .object({
    reasonCategory: z.enum(PAYEE_INFO_VIEW_REASON_CATEGORY_VALUES).optional(),
    reasonText: z.string(),
  })
  .superRefine((values, ctx) => {
    if (!values.reasonCategory) {
      ctx.addIssue({ code: "custom", path: ["reasonCategory"], message: "사유 분류를 골라주세요." });
    }
    const text = values.reasonText.trim();
    if (text.length === 0) {
      ctx.addIssue({ code: "custom", path: ["reasonText"], message: "열람이 필요한 이유를 입력해주세요." });
    } else if (text.length > 1000) {
      ctx.addIssue({ code: "custom", path: ["reasonText"], message: "사유는 1,000자까지 쓸 수 있어요." });
    }
  });

export type ViewPayeeReasonFormValues = z.infer<typeof viewPayeeReasonSchema>;
