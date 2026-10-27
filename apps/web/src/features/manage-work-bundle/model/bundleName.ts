import { z } from "zod";

import { WORK_BUNDLE_NAME_MAX_LENGTH } from "@/entities/work";

/** 서버가 세는 방식의 글자 수 — 앞뒤 공백을 걷은 뒤 코드 포인트 수. `.length` 는 이모지를 2자로 센다. */
export function countBundleNameChars(value: string): number {
  return Array.from(value.trim()).length;
}

/** 묶음 이름 폼. 서버는 앞뒤 공백을 걷어 저장하고 빈 이름을 받지 않으며, 같은 이름은 허용한다. */
export const workBundleNameSchema = z.object({
  name: z
    .string()
    .refine((value) => countBundleNameChars(value) > 0, "묶음 이름을 입력해 주세요")
    .refine(
      (value) => countBundleNameChars(value) <= WORK_BUNDLE_NAME_MAX_LENGTH,
      `이름은 ${WORK_BUNDLE_NAME_MAX_LENGTH}자까지 쓸 수 있어요`,
    ),
});

export type WorkBundleNameFormValues = z.infer<typeof workBundleNameSchema>;
