import type { components } from "@ai-character-chat/api-types";

import type { StartingSetupValues, StatDefValues, StoryBuilderFormValues } from "./schema";

type StoryDraftResponse = components["schemas"]["StoryDraftResponse"];
type StartingSetupDraftItem = components["schemas"]["StartingSetupDraftItem"];
type StatDefDraftItem = components["schemas"]["StatDefDraftItem"];

/** `formToServer.ts`의 `StoryStartingSetupPayload`와 대칭 — endings는 US-095 몫이라 제외한다. */
type StoryStartingSetupResponse = Pick<
  StartingSetupDraftItem,
  "id" | "name" | "prologue" | "openingMessage" | "playguide" | "suggestedReplies" | "statDefs"
>;

function fromApiStatDef(stat: StatDefDraftItem): StatDefValues {
  return {
    id: stat.id,
    name: stat.name,
    icon: stat.icon,
    color: stat.color,
    min: stat.minValue,
    max: stat.maxValue,
    initial: stat.initialValue,
    unit: stat.unit ?? undefined,
    description: stat.description,
  };
}

// BE가 이미 order 기준으로 정렬해 배열로 내려주므로, 별도 정렬 없이 배열 순서를 그대로 복원한다.
function fromApiStartingSetup(setup: StoryStartingSetupResponse): StartingSetupValues {
  return {
    id: setup.id,
    name: setup.name,
    prologue: setup.prologue,
    openingSituation: setup.openingMessage ?? undefined,
    playGuide: setup.playguide ?? undefined,
    suggestedReplies: setup.suggestedReplies,
    stats: setup.statDefs.map(fromApiStatDef),
  };
}

/**
 * `GET /contents/{id}/draft` 응답 중 profile/storySetting/startingSetups/registration 부분 ->
 * 폼 defaultValues(techspec-overview.md §8.1, 순수 함수). keywordNotes/shortcuts는 아직 폼 스키마에
 * 없다 — US-094가 이 함수에 그 매핑을 추가한다(`formToServer.ts` 노트 참고).
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
  > & { startingSetups: StoryStartingSetupResponse[] },
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
    startingSetups: data.startingSetups.map(fromApiStartingSetup),
    registration: {
      description: data.description,
      genre: data.genreId,
      target: data.target,
      hashtags: data.hashtags,
      visibility: data.visibility,
    },
  };
}
