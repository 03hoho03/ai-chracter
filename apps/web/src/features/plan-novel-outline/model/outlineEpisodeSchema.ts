import { z } from "zod";

import { countOutlineChars, OUTLINE_GOAL_MAX_LENGTH, OUTLINE_SUMMARY_MAX_LENGTH, type OutlineEpisodeDraft } from "./outlineEdits";

/** 구성안 화 하나의 글 고치기 폼. 서버처럼 앞뒤 공백을 걷고 센다 — 제목·줄거리는 비울 수 없고, 목표는 비워도 된다.
 * 상한을 넘었다는 이슈에는 그 상한(`params.maxLength`)을 실어 둔다 — 저장 전 점검(`toOutlineProblems`)이 화 번호를
 * 붙인 "제목이 N자를 넘어요" 꼴로 다시 말한다. */
export function createOutlineEpisodeSchema(titleMaxLength: number) {
  return z.object({
    title: z
      .string()
      .refine((value) => countOutlineChars(value) > 0, "제목을 적어주세요")
      .refine((value) => countOutlineChars(value) <= titleMaxLength, {
        message: `제목은 ${titleMaxLength.toLocaleString()}자까지 쓸 수 있어요`,
        params: { maxLength: titleMaxLength },
      }),
    summary: z
      .string()
      .refine((value) => countOutlineChars(value) > 0, "줄거리를 적어주세요")
      .refine((value) => countOutlineChars(value) <= OUTLINE_SUMMARY_MAX_LENGTH, {
        message: `줄거리는 ${OUTLINE_SUMMARY_MAX_LENGTH.toLocaleString()}자까지 쓸 수 있어요`,
        params: { maxLength: OUTLINE_SUMMARY_MAX_LENGTH },
      }),
    goal: z.string().refine((value) => countOutlineChars(value) <= OUTLINE_GOAL_MAX_LENGTH, {
      message: `목표는 ${OUTLINE_GOAL_MAX_LENGTH}자까지 쓸 수 있어요`,
      params: { maxLength: OUTLINE_GOAL_MAX_LENGTH },
    }),
  });
}

export type OutlineEpisodeFormValues = z.infer<ReturnType<typeof createOutlineEpisodeSchema>>;

/** 상한을 넘은 칸을 저장 전 점검 문장에서 부르는 말(조사까지). */
const OVER_LIMIT_SUBJECTS = new Map<PropertyKey | undefined, string>([
  ["title", "제목이"],
  ["summary", "줄거리가"],
  ["goal", "목표가"],
]);

/** 저장하기 전에 고쳐야 할 것 — 화 번호를 붙인 문장들. 비었으면 저장할 수 있다. 화마다 고치기 폼과 같은 스키마로
 * 검사하고, 화 수 상한만 여기서 본다. */
export function toOutlineProblems(
  episodes: readonly OutlineEpisodeDraft[],
  ordinals: readonly number[],
  limits: { titleMaxLength: number; maxEpisodes: number },
): string[] {
  if (episodes.length > limits.maxEpisodes) {
    return [`구성안은 ${limits.maxEpisodes.toLocaleString()}화까지예요. 화를 합치거나 지워주세요.`];
  }
  const schema = createOutlineEpisodeSchema(limits.titleMaxLength);
  return episodes.flatMap((episode, index) => {
    const result = schema.safeParse(episode);
    if (result.success) return [];
    const label = `${ordinals[index] ?? index + 1}화`;
    return result.error.issues.map((issue) => {
      const maxLength: unknown = issue.code === "custom" ? issue.params?.maxLength : undefined;
      const subject = OVER_LIMIT_SUBJECTS.get(issue.path[0]);
      if (typeof maxLength === "number" && subject !== undefined) return `${label} ${subject} ${maxLength}자를 넘어요.`;
      return `${label} ${issue.message}.`;
    });
  });
}
