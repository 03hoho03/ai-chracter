import { z } from "zod";

import { SCENE_PURPOSE_MAX_LENGTH, SCENE_SUMMARY_MAX_LENGTH } from "./episodeScenes";
import { countOutlineChars } from "./outlineEdits";

/** 장면 하나의 글 고치기 폼. 서버처럼 앞뒤 공백을 걷고 센다 — 제목·내용은 비울 수 없고, 목적은 비워도 된다. */
export function createSceneSchema(titleMaxLength: number) {
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
      .refine((value) => countOutlineChars(value) > 0, "내용을 적어주세요")
      .refine(
        (value) => countOutlineChars(value) <= SCENE_SUMMARY_MAX_LENGTH,
        `내용은 ${SCENE_SUMMARY_MAX_LENGTH.toLocaleString()}자까지 쓸 수 있어요`,
      ),
    purpose: z
      .string()
      .refine((value) => countOutlineChars(value) <= SCENE_PURPOSE_MAX_LENGTH, `목적은 ${SCENE_PURPOSE_MAX_LENGTH}자까지 쓸 수 있어요`),
  });
}

export type SceneFormValues = z.infer<ReturnType<typeof createSceneSchema>>;
