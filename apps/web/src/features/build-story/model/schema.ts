import { z } from "zod";

/**
 * techspec-builder-story.md §1 — `promptTemplate`이 'custom'일 때 `worldSetting`/`developmentExample`은
 * 화면 전환처럼 값은 폼 상태에 보존하되 검증에서만 제외하고, customPrompt를 필수로 요구한다.
 * 'basic'/'emotional'/'simulation'일 때는 반대로 worldSetting을 필수로 요구하고 customPrompt는 제외한다.
 * developmentExample(고급설정)은 어느 템플릿에서도 필수가 아니다.
 */
export const storySettingSchema = z
  .object({
    promptTemplate: z.enum(["basic", "emotional", "simulation", "custom"]).default("basic"),
    worldSetting: z.string().optional(),
    developmentExample: z.string().optional(),
    customPrompt: z.string().optional(),
  })
  .superRefine((value, ctx) => {
    if (value.promptTemplate === "custom") {
      if (!value.customPrompt || value.customPrompt.length < 1) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["customPrompt"],
          message: "커스텀 프롬프트를 입력해 주세요.",
        });
      }
      return;
    }
    if (!value.worldSetting || value.worldSetting.length < 1) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["worldSetting"],
        message: "세계관 설정을 입력해 주세요.",
      });
    }
  });

export const storyBuilderSchema = z.object({
  profile: z.object({
    name: z.string().min(1),
    oneLiner: z.string().min(1),
    image: z.object({ assetId: z.string() }).nullable(),
  }),
  storySetting: storySettingSchema,
  registration: z.object({
    description: z.string().min(1),
    // 실제 StoryDraftPayload/Response의 genreId/target 계약(string|null / ContentTarget|null)에 맞춰
    // profile.image와 동일한 이유로 nullable로 둔다(US-091 캐릭터 빌더와 동일한 판단 — 초안 상태에선
    // 아직 선택 전일 수 있고, 발행 시 필수 검증은 이 스키마를 쓰는 이후 빌더 UI 스토리의 몫이다).
    genre: z.string().nullable(),
    target: z.enum(["female", "male", "all"]).nullable(),
    hashtags: z.array(z.string()).default([]),
    visibility: z.enum(["public", "link", "private"]).default("private"),
  }),
});

export type StorySettingValues = z.infer<typeof storySettingSchema>;
export type StoryBuilderFormValues = z.infer<typeof storyBuilderSchema>;
