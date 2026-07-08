import type { components } from "@ai-character-chat/api-types";

import type {
  EndingValues,
  KeywordNoteValues,
  RuleListItemValues,
  SingleRuleValues,
  StartingSetupValues,
  StatDefValues,
  StoryBuilderFormValues,
} from "./schema";

type StoryDraftResponse = components["schemas"]["StoryDraftResponse"];
type StartingSetupDraftItem = components["schemas"]["StartingSetupDraftItem"];
type StatDefDraftItem = components["schemas"]["StatDefDraftItem"];
type KeywordNoteDraftItem = components["schemas"]["KeywordNoteDraftItem"];
type EndingDraftItem = components["schemas"]["EndingDraftItem"];
type EndingRuleDraftItem = components["schemas"]["EndingRuleDraftItem"];
type EndingRuleGroupDraftItem = components["schemas"]["EndingRuleGroupDraftItem"];

// `formToServer.ts`의 OPERATOR_TO_API와 반대 방향(서버 -> FE) 매핑. 서버 enum이 애초에 5개뿐이라
// (gte/lte/eq/gt/lt) 이 Record는 항상 완전하다 — "!="을 만들어낼 방법이 없다.
const OPERATOR_FROM_API: Record<EndingRuleDraftItem["operator"], SingleRuleValues["operator"]> = {
  gte: ">=",
  lte: "<=",
  eq: "==",
  gt: ">",
  lt: "<",
};

function fromApiSingleRule(dto: EndingRuleDraftItem): SingleRuleValues {
  return {
    kind: "rule",
    id: dto.id,
    statId: dto.statId,
    operator: OPERATOR_FROM_API[dto.operator],
    value: dto.threshold,
    nextOp: dto.nextOp ?? null,
  };
}

function fromApiRuleListItem(dto: EndingRuleDraftItem | EndingRuleGroupDraftItem): RuleListItemValues {
  if (dto.kind === "group") {
    return { kind: "group", id: dto.id, rules: dto.rules.map(fromApiSingleRule), nextOp: dto.nextOp ?? null };
  }
  return fromApiSingleRule(dto);
}

// BE가 이미 order 기준으로 정렬해 배열로 내려주므로, 별도 정렬 없이 배열 순서를 그대로 복원한다.
function fromApiEnding(dto: EndingDraftItem): EndingValues {
  return {
    id: dto.id,
    name: dto.name,
    turnGate: dto.turnCountGate,
    judgePrompt: dto.judgmentPrompt,
    statRules: dto.statRules.map(fromApiRuleListItem),
    epilogue: dto.epilogue ?? undefined,
    hint: dto.hint ?? undefined,
  };
}

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

// startingSetupId === null이면 global, 아니면 startingSetup 스코프로 역변환한다(techspec §1.3 [확정] 매핑).
function fromApiKeywordNote(note: KeywordNoteDraftItem): KeywordNoteValues {
  return {
    id: note.id,
    content: note.infoText,
    triggerKeywords: note.triggerKeywords,
    scope:
      note.startingSetupId === null
        ? { kind: "global" }
        : { kind: "startingSetup", startingSetupId: note.startingSetupId },
  };
}

// BE가 이미 order 기준으로 정렬해 배열로 내려주므로, 별도 정렬 없이 배열 순서를 그대로 복원한다.
function fromApiStartingSetup(setup: StartingSetupDraftItem): StartingSetupValues {
  return {
    id: setup.id,
    name: setup.name,
    prologue: setup.prologue,
    openingSituation: setup.openingMessage ?? undefined,
    playGuide: setup.playguide ?? undefined,
    suggestedReplies: setup.suggestedReplies,
    stats: setup.statDefs.map(fromApiStatDef),
    endings: setup.endings.map(fromApiEnding),
  };
}

/**
 * `GET /contents/{id}/draft` 응답 중 profile/storySetting/startingSetups/keywordNotes/shortcuts/
 * registration 부분 -> 폼 defaultValues(techspec-overview.md §8.1, 순수 함수).
 *
 * `settingText`/`developmentExample`/`customPrompt`는 promptTemplate 값과 무관하게 서버가 저장된
 * 값을 그대로 돌려주므로(§1 "값은 보존") 여기서 분기 없이 그대로 복원한다 — 필수 여부 분기는
 * `schema.ts`의 `storySettingSchema` superRefine에서만 적용된다.
 *
 * endings(US-095)가 startingSetups의 마지막 남은 필드였다 — 이제 전체 `StoryDraftResponse`를 그대로
 * 받으므로 US-092~094가 쓰던 `Pick<...>` 좁히기가 더 필요 없다(`formToServer.ts`와 대칭).
 */
export function serverToForm(data: StoryDraftResponse): StoryBuilderFormValues {
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
    keywordNotes: data.keywordNotes.map(fromApiKeywordNote),
    shortcuts: data.shortcuts,
    registration: {
      description: data.description,
      genre: data.genreId,
      target: data.target,
      hashtags: data.hashtags,
      visibility: data.visibility,
    },
  };
}
