import type { components } from "@ai-character-chat/api-types";

import type { KeywordNoteValues, StartingSetupValues, StatDefValues, StoryBuilderFormValues } from "./schema";

type StoryDraftPayload = components["schemas"]["StoryDraftPayload"];
type StartingSetupDraftItem = components["schemas"]["StartingSetupDraftItem"];
type StatDefDraftItem = components["schemas"]["StatDefDraftItem"];
type KeywordNoteDraftItem = components["schemas"]["KeywordNoteDraftItem"];

/**
 * startingSetups 안의 `endings`는 US-095 몫이라 `StartingSetupDraftItem`을 그대로 쓰지 않고 지금까지
 * (US-093/094) 채우는 필드만 Pick했다. keywordNotes/shortcuts(US-094)는 `KeywordNoteDraftItem`/
 * `ShortcutDraftItem`을 그대로 다 채우므로 Pick 없이 `StoryDraftPayload`의 필드로 바로 포함한다.
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
  | "keywordNotes"
  | "shortcuts"
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

// scope.kind === 'global'이면 null, 아니면 참조한 시작설정 id로 변환한다(techspec §1.3 [확정] 매핑).
function toApiKeywordNote(note: KeywordNoteValues): KeywordNoteDraftItem {
  return {
    id: note.id,
    infoText: note.content,
    triggerKeywords: note.triggerKeywords,
    startingSetupId: note.scope.kind === "global" ? null : note.scope.startingSetupId,
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
 * 폼값 -> `PATCH /contents/{id}/draft` payload 중 profile/storySetting/startingSetups/
 * keywordNotes/shortcuts/registration 부분(techspec-overview.md §8.1, 순수 함수).
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
    keywordNotes: values.keywordNotes.map(toApiKeywordNote),
    shortcuts: values.shortcuts,
    description: values.registration.description,
    genreId: values.registration.genre,
    target: values.registration.target,
    hashtags: values.registration.hashtags,
    visibility: values.registration.visibility,
  };
}
