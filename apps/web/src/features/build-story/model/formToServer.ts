import type { components } from "@ai-character-chat/api-types";

import type { StartingSetupValues, StatDefValues, StoryBuilderFormValues } from "./schema";

type StoryDraftPayload = components["schemas"]["StoryDraftPayload"];
type StartingSetupDraftItem = components["schemas"]["StartingSetupDraftItem"];
type StatDefDraftItem = components["schemas"]["StatDefDraftItem"];

/**
 * keywordNotes/shortcuts는 아직 폼 스키마에 없다 — US-094가 이 함수에 그 매핑을 추가해 반환 타입을
 * `StoryDraftPayload` 전체로 넓힌다. startingSetups 안의 `endings`도 같은 이유로 US-095 몫이라
 * `StartingSetupDraftItem`을 그대로 쓰지 않고 이 스토리(US-093)가 채우는 필드만 Pick했다.
 */
export type StoryStartingSetupPayload = Pick<
  StartingSetupDraftItem,
  "id" | "name" | "prologue" | "openingMessage" | "playguide" | "suggestedReplies" | "statDefs"
>;

export type StoryBuilderDraftPayload = Pick<
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
> & {
  startingSetups: StoryStartingSetupPayload[];
};

function toApiStatDef(stat: StatDefValues): StatDefDraftItem {
  return {
    id: stat.id,
    name: stat.name,
    icon: stat.icon,
    color: stat.color,
    minValue: stat.min,
    maxValue: stat.max,
    initialValue: stat.initial,
    unit: stat.unit ?? null,
    description: stat.description,
  };
}

// order는 서버 스키마에 별도 숫자 필드가 없다 — 배열 인덱스 자체가 order다(US-091 캐릭터 빌더와 동일).
function toApiStartingSetup(setup: StartingSetupValues): StoryStartingSetupPayload {
  return {
    id: setup.id,
    name: setup.name,
    prologue: setup.prologue,
    openingMessage: setup.openingSituation ?? null,
    playguide: setup.playGuide ?? null,
    suggestedReplies: setup.suggestedReplies,
    statDefs: setup.stats.map(toApiStatDef),
  };
}

/**
 * 폼값 -> `PATCH /contents/{id}/draft` payload 중 profile/storySetting/startingSetups/registration
 * 부분(techspec-overview.md §8.1, 순수 함수).
 */
export function formToServer(values: StoryBuilderFormValues): StoryBuilderDraftPayload {
  return {
    name: values.profile.name,
    oneLiner: values.profile.oneLiner,
    thumbnailAssetId: values.profile.image?.assetId ?? null,
    promptTemplate: values.storySetting.promptTemplate,
    settingText: values.storySetting.worldSetting ?? null,
    developmentExample: values.storySetting.developmentExample ?? null,
    customPrompt: values.storySetting.customPrompt ?? null,
    startingSetups: values.startingSetups.map(toApiStartingSetup),
    description: values.registration.description,
    genreId: values.registration.genre,
    target: values.registration.target,
    hashtags: values.registration.hashtags,
    visibility: values.registration.visibility,
  };
}
