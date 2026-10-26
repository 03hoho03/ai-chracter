import type { components } from "@ai-character-chat/api-types";
import { z } from "zod";

export type AdminPromptDraftResponse = components["schemas"]["AdminPromptDraftResponse"];
export type AdminPromptDraftUpsertRequest = components["schemas"]["AdminPromptDraftUpsertRequest"];

// 서버의 게시 시점 라벨 검증을 그대로 거울: stop_sequence가 `\n{user_label}:`로
// 파생되므로 라벨은 비어 있거나 개행·':'을 포함할 수 없다. 서버가 결국 다시 검증하지만,
// 게시 시점까지 기다리지 않고 여기서 먼저 막는다.
const promptLabelSchema = z
  .string()
  .trim()
  .min(1, "라벨을 입력하세요.")
  .refine((value) => !value.includes("\n") && !value.includes(":"), "개행이나 ':'을 포함할 수 없어요.");

// channel/scope/slot/variant/conditional은 코드가 고정한 값이라 어드민이 바꾸지 않는다 —
// 폼은 이 값을 그대로 들고 있다가 저장 시 되돌려 보낼 뿐이다. body와 order만 실제로 편집된다.
const promptSectionSchema = z.object({
  channel: z.string(),
  scope: z.string(),
  slot: z.string(),
  variant: z.string(),
  body: z.string().refine((value) => value.trim().length > 0, "본문을 입력하세요."), // 서버의 빈 본문 검증 거울
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

/** 초안 저장이 그 사이 다른 곳의 저장을 덮지 않게 하는 방법. `check` 는 화면이 초안을 받을 때 함께 받은 저장 해시를 돌려보내
 * 그 뒤 다른 저장이 있었으면 서버가 409 로 멈추게 한다(null 은 "저장된 초안이 없어야 한다"). `overwrite` 는 운영자가 그 충돌을
 * 보고 덮어쓰기를 고른 뒤라 해시 칸을 빼 서버가 검사하지 않게 한다. */
export type DraftSaveGuard = { kind: "check"; savedDraftHash: string | null } | { kind: "overwrite" };

export function formToServer(values: PromptSetFormValues, guard: DraftSaveGuard): AdminPromptDraftUpsertRequest {
  const body = { labels: values.labels, sections: values.sections };
  return guard.kind === "check" ? { ...body, baseDraftHash: guard.savedDraftHash } : body;
}
