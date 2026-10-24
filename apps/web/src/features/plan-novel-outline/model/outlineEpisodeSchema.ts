import { z } from "zod";

import { countOutlineChars, OUTLINE_GOAL_MAX_LENGTH, OUTLINE_SUMMARY_MAX_LENGTH } from "./outlineEdits";

/** 구성안 화 하나의 글 고치기 폼. 서버처럼 앞뒤 공백을 걷고 센다 — 제목·줄거리는 비울 수 없고, 목표는 비워도 된다. */
export function createOutlineEpisodeSchema(titleMaxLength: number) {
  return z.object({
    title: z
      .string()
      .refine((value) => countOutlineChars(value) > 0, "제목을 적어주세요")
      .refine(
        (value) => countOutlineChars(value) <= titleMaxLength,
        `제목은 ${titleMaxLength.toLocaleString()}자까지 쓸 수 있어요`,
      ),
    summary: z
      .string()
      .refine((value) => countOutlineChars(value) > 0, "줄거리를 적어주세요")
      .refine(
        (value) => countOutlineChars(value) <= OUTLINE_SUMMARY_MAX_LENGTH,
        `줄거리는 ${OUTLINE_SUMMARY_MAX_LENGTH.toLocaleString()}자까지 쓸 수 있어요`,
      ),
    goal: z
      .string()
      .refine((value) => countOutlineChars(value) <= OUTLINE_GOAL_MAX_LENGTH, `목표는 ${OUTLINE_GOAL_MAX_LENGTH}자까지 쓸 수 있어요`),
  });
}

export type OutlineEpisodeFormValues = z.infer<ReturnType<typeof createOutlineEpisodeSchema>>;
