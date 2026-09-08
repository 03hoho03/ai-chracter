import { z } from "zod";

/** 서버(`apps/api/src/api/moderation/schemas.py`)의 `reason_text: str = Field(min_length=1)`와 짝이다.
 * 서버는 트림하지 않아 공백만 있는 사유도 통과시키므로 트림은 이쪽이 진다. */
export const submitAppealSchema = z.object({
  reasonText: z.string().trim().min(1, { message: "이의제기 사유를 입력해주세요" }),
});

export type SubmitAppealFormValues = z.infer<typeof submitAppealSchema>;
