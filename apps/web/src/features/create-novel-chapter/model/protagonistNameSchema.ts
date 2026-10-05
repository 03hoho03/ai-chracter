import { z } from "zod";

import { userNameError } from "@/shared/lib/text/authorMacros";

/** 주인공 이름 폼. 서버와 같은 규칙이다 — 앞뒤 공백을 걷고 1자 이상, 상한은 상세가 준 값, 그리고 대화 프로필
 * 이름과 같은 금지 문자 규칙(작가 글의 `{{user}}` 자리에 들어가는 이름이라 거기서 표기로 읽히는 문자를 막는다).
 * 상한은 서버 응답에서만 읽으므로 스키마를 그 값으로 만든다. */
export function createProtagonistNameSchema(maxLength: number) {
  return z.object({
    protagonistName: z
      .string()
      .trim()
      .min(1, { message: "이름을 입력해주세요" })
      .max(maxLength, { message: `이름은 ${maxLength}자 이내로 입력해주세요` })
      .superRefine((value, context) => {
        const error = userNameError(value);
        if (error !== null) context.addIssue({ code: "custom", message: error });
      }),
  });
}

export type ProtagonistNameFormValues = z.infer<ReturnType<typeof createProtagonistNameSchema>>;
