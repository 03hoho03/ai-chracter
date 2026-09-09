import type { components } from "@ai-character-chat/api-types";
import { z } from "zod";

export type AdminPromptDraftResponse = components["schemas"]["AdminPromptDraftResponse"];
export type AdminPromptDraftUpsertRequest = components["schemas"]["AdminPromptDraftUpsertRequest"];

// R-5(prompt-db-goal-prompt.md §9-2)를 그대로 거울: stop_sequence가 `\n{user_label}:`로
// 파생되므로(§4-5) 라벨은 비어 있거나 개행·':'을 포함할 수 없다. 서버가 결국 다시 검증하지만,
// 게시 시점까지 기다리지 않고 여기서 먼저 막는다.
const promptLabelSchema = z
  .string()
  .trim()
  .min(1, "라벨을 입력하세요.")
  .refine((value) => !value.includes("\n") && !value.includes(":"), "개행이나 ':'을 포함할 수 없어요.");

// channel/scope/slot/variant/conditional은 코드가 고정한 값이라(D-7) 어드민이 바꾸지 않는다 —
// 폼은 이 값을 그대로 들고 있다가 저장 시 되돌려 보낼 뿐이다. body와 order만 실제로 편집된다.
const promptSectionSchema = z.object({
  channel: z.string(),
  scope: z.string(),
  slot: z.string(),
  variant: z.string(),
  body: z.string().refine((value) => value.trim().length > 0, "본문을 입력하세요."), // R-3 거울
  conditional: z.boolean(),
  order: z.number(),
});

export const promptSetFormSchema = z.object({
  labels: z.object({
    userLabel: promptLabelSchema,
    storyAssistantLabel: promptLabelSchema,
    storyExampleLabel: promptLabelSchema,
    characterAssistantLabel: promptLabelSchema,
  }),
  sections: z.array(promptSectionSchema),
});

export type PromptSetFormValues = z.infer<typeof promptSetFormSchema>;

export function serverToForm(data: AdminPromptDraftResponse): PromptSetFormValues {
  return { labels: data.labels, sections: data.sections };
}

export function formToServer(values: PromptSetFormValues): AdminPromptDraftUpsertRequest {
  return { labels: values.labels, sections: values.sections };
}
