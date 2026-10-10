import { z } from "zod";

import { personaNameIssue } from "@/entities/persona";

/** 첫 대화 프로필의 이름 하나만 받는 폼. 규칙은 프로필 관리 화면과 같다(`personaNameIssue`). */
export const firstPersonaNameSchema = z.object({
  name: z.string().superRefine((value, context) => {
    const issue = personaNameIssue(value);
    if (issue !== null) context.addIssue({ code: "custom", message: issue });
  }),
});

export type FirstPersonaNameFormValues = z.infer<typeof firstPersonaNameSchema>;
