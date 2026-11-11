import { z } from "zod";

import { SCENE_PURPOSE_MAX_LENGTH, SCENE_SUMMARY_MAX_LENGTH, type SceneDraft } from "./episodeScenes";
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

/** 저장 전에 고칠 것 — 서버가 같은 이유로 막는 것을 장면 번호로 먼저 짚는다. 고치기 폼과 같은 스키마로 검사하므로 대개
 * 비어 있다. */
export function toSceneProblems(scenes: readonly SceneDraft[], limits: { titleMaxLength: number }): string[] {
  const schema = createSceneSchema(limits.titleMaxLength);
  return scenes.flatMap((scene, index) => {
    const result = schema.safeParse(scene);
    return result.success ? [] : result.error.issues.map((issue) => `장면 ${index + 1} ${issue.message}.`);
  });
}
