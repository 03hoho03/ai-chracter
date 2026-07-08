import type { components } from "@ai-character-chat/api-types";

import type { StoryBuilderFormValues } from "./schema";

type StoryDraftPayload = components["schemas"]["StoryDraftPayload"];

/**
 * 폼값 -> `PATCH /contents/{id}/draft` payload 중 profile/storySetting/registration 부분
 * (techspec-overview.md §8.1, 순수 함수). startingSetups/keywordNotes/shortcuts는 아직 폼 스키마에
 * 없다 — 이후 스토리(US-093~095)가 이 함수에 그 매핑을 추가해 반환 타입을 `StoryDraftPayload` 전체로
 * 넓힌다(US-091 캐릭터 빌더 노트: order는 배열 인덱스 자체라 별도 숫자 필드 계산이 필요 없었던 것과
 * 같은 이유로, 여기도 값 보존/복원 외에 별도 변환 로직이 필요 없다).
 */
export type StoryProfileSettingRegistrationPayload = Pick<
  StoryDraftPayload,
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
>;

export function formToServer(
  values: StoryBuilderFormValues,
): StoryProfileSettingRegistrationPayload {
  return {
    name: values.profile.name,
    oneLiner: values.profile.oneLiner,
    thumbnailAssetId: values.profile.image?.assetId ?? null,
    promptTemplate: values.storySetting.promptTemplate,
    settingText: values.storySetting.worldSetting ?? null,
    developmentExample: values.storySetting.developmentExample ?? null,
    customPrompt: values.storySetting.customPrompt ?? null,
    description: values.registration.description,
    genreId: values.registration.genre,
    target: values.registration.target,
    hashtags: values.registration.hashtags,
    visibility: values.registration.visibility,
  };
}
