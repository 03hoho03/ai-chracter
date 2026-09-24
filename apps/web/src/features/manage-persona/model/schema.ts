import { z } from "zod";

import { PERSONA_DESCRIPTION_MAX_LENGTH, PERSONA_NAME_MAX_LENGTH } from "@/entities/persona";

import { PERSONA_GENDER_OPTIONS } from "./personaGenderOption";

/** persona-goal-prompt.md UP-5 — BE `persona/schemas.py`와 같은 규칙: 이름은 trim 뒤 1~20자, `:`·`\n`·`\r`
 * 금지(전각 `：`는 허용), 설명은 trim 뒤 0~500자(UP-22 선택). */
export const personaFormSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, { message: "이름을 입력해주세요" })
    .max(PERSONA_NAME_MAX_LENGTH, { message: `이름은 ${PERSONA_NAME_MAX_LENGTH}자 이내로 입력해주세요` })
    .refine((value) => !/[:\r\n]/.test(value), { message: "이름에는 콜론(:)이나 줄바꿈을 쓸 수 없어요" }),
  gender: z.enum(PERSONA_GENDER_OPTIONS),
  description: z
    .string()
    .trim()
    .max(PERSONA_DESCRIPTION_MAX_LENGTH, {
      message: `설명은 ${PERSONA_DESCRIPTION_MAX_LENGTH}자 이내로 입력해주세요`,
    }),
  /** 생성 폼에서만 보인다. 편집 폼에서는 `formToUpdateRequest`가 버린다. */
  setAsDefault: z.boolean(),
});

export type PersonaFormValues = z.infer<typeof personaFormSchema>;
