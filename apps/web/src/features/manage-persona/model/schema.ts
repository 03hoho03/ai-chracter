import { z } from "zod";

import { PERSONA_DESCRIPTION_MAX_LENGTH, PERSONA_NAME_MAX_LENGTH } from "@/entities/persona";
import { userNameError } from "@/shared/lib/text/authorMacros";

import { PERSONA_GENDER_OPTIONS } from "./personaGenderOption";

/** 설명 칸이 서버가 세는 방식 그대로 센 글자 수 — 앞뒤 공백을 잘라낸 뒤 코드 포인트 수. JS `.length`(UTF-16)로
 * 세면 이모지가 2자가 돼 서버가 받는 설명을 화면이 먼저 막는다. 카운터와 아래 검증이 이 값을 함께 쓴다. */
export function countPersonaDescriptionChars(value: string): number {
  return Array.from(value.trim()).length;
}

/** BE `persona/schemas.py`와 같은 규칙: 이름은 trim 뒤 1~20자이고 작가 글의 `{{user}}` 자리에 들어갈 수 있어야
 * 한다(막는 문자와 이유는 `userNameError`), 설명은 trim 뒤 0~500자(선택). */
export const personaFormSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, { message: "이름을 입력해주세요" })
    .max(PERSONA_NAME_MAX_LENGTH, { message: `이름은 ${PERSONA_NAME_MAX_LENGTH}자 이내로 입력해주세요` })
    .superRefine((value, context) => {
      const error = userNameError(value);
      if (error !== null) context.addIssue({ code: "custom", message: error });
    }),
  gender: z.enum(PERSONA_GENDER_OPTIONS),
  description: z
    .string()
    .trim()
    .refine((value) => countPersonaDescriptionChars(value) <= PERSONA_DESCRIPTION_MAX_LENGTH, {
      message: `설명은 ${PERSONA_DESCRIPTION_MAX_LENGTH}자 이내로 입력해주세요`,
    }),
  /** 생성 폼에서만 보인다. 편집 폼에서는 `formToUpdateRequest`가 버린다. */
  setAsDefault: z.boolean(),
});

export type PersonaFormValues = z.infer<typeof personaFormSchema>;
