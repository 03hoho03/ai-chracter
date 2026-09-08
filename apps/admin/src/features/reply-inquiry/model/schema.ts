import { z } from "zod";

/** 서버(`apps/api/src/api/inquiry/schemas.py`)의 `reply_body: str = Field(min_length=1)`와 짝이다.
 * 서버는 트림하지 않아 공백만 있는 답변도 통과시키므로 트림은 이쪽이 진다. */
export const replyInquirySchema = z.object({
  replyBody: z.string().trim().min(1, { message: "답변 내용을 입력해주세요" }),
});

export type ReplyInquiryFormValues = z.infer<typeof replyInquirySchema>;
