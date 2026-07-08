import type { components } from "@ai-character-chat/api-types";

import type { StoryBuilderFormValues } from "./schema";

type StoryDraftResponse = components["schemas"]["StoryDraftResponse"];

/**
 * `GET /contents/{id}/draft` 응답 중 profile/storySetting/registration 부분 -> 폼 defaultValues
 * (techspec-overview.md §8.1, 순수 함수). startingSetups/keywordNotes/shortcuts는 아직 폼 스키마에
 * 없다 — 이후 스토리(US-093~095)가 이 함수에 그 매핑을 추가한다(`formToServer.ts` 노트 참고).
 *
 * `settingText`/`developmentExample`/`customPrompt`는 promptTemplate 값과 무관하게 서버가 저장된
 * 값을 그대로 돌려주므로(§1 "값은 보존") 여기서 분기 없이 그대로 복원한다 — 필수 여부 분기는
 * `schema.ts`의 `storySettingSchema` superRefine에서만 적용된다.
 */
export function serverToForm(
  data: Pick<
    StoryDraftResponse,
    | "name"
    | "oneLiner"
    | "thumbnailAssetId"
    | "promptTemplate"
    | "settingText"
    | "developmentExample"
    | "customPrompt"
    | "description"
    | "genreId"
    | "target"
    | "hashtags"
    | "visibility"
  >,
): StoryBuilderFormValues {
  return {
    profile: {
      name: data.name,
      oneLiner: data.oneLiner,
      image: data.thumbnailAssetId ? { assetId: data.thumbnailAssetId } : null,
    },
    storySetting: {
      promptTemplate: data.promptTemplate,
      worldSetting: data.settingText ?? undefined,
      developmentExample: data.developmentExample ?? undefined,
      customPrompt: data.customPrompt ?? undefined,
    },
    registration: {
      description: data.description,
      genre: data.genreId,
      target: data.target,
      hashtags: data.hashtags,
      visibility: data.visibility,
    },
  };
}
