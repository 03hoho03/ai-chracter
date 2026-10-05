import { z } from "zod";

import { countChapterChars } from "./chapterBody";

/** AI 수정 지시 폼. 서버와 같은 규칙이다 — 앞뒤 공백을 걷고 1자 이상, 상한은 상세가 준 값(코드 포인트로 센다).
 * 입력칸에 `maxLength` 를 두지 않는다 — 붙여넣은 글이 말없이 잘리지 않고 오류로 보이게. */
export function createAiEditInstructionSchema(maxLength: number) {
  return z.object({
    instruction: z
      .string()
      .trim()
      .min(1, { message: "어떻게 고칠지 적어주세요" })
      .refine((value) => countChapterChars(value) <= maxLength, {
        message: `${maxLength.toLocaleString()}자 이내로 적어주세요`,
      }),
  });
}

export type AiEditInstructionFormValues = z.infer<ReturnType<typeof createAiEditInstructionSchema>>;
