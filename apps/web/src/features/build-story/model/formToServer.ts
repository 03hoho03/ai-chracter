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

type StoryDraftPayload = components["schemas"]["StoryDraftPayload"];
type StartingSetupDraftItem = components["schemas"]["StartingSetupDraftItem"];
type StatDefDraftItem = components["schemas"]["StatDefDraftItem"];
type KeywordNoteDraftItem = components["schemas"]["KeywordNoteDraftItem"];
type EndingDraftItem = components["schemas"]["EndingDraftItem"];
type EndingRuleDraftItem = components["schemas"]["EndingRuleDraftItem"];
type EndingRuleGroupDraftItem = components["schemas"]["EndingRuleGroupDraftItem"];

// endings(US-095)가 startingSetups의 마지막 남은 필드였다 — 이제 storyBuilderSchema가 StoryDraftPayload의
// 모든 필드를 채우므로 US-092~094가 쓰던 `Pick<...>` 좁히기가 더 필요 없다(US-092 CLAUDE.md 메모 참고).
export type StoryBuilderDraftPayload = StoryDraftPayload;

// FE는 techspec 의사코드의 비교 연산자 기호(>=, <= ...)를 쓰고 서버는 EndingRuleOperator(gte/lte/eq/gt/lt,
// DB 컬럼 그대로)를 쓴다 — entities/chat-room/model/toChatRoomState.ts의 OPERATOR_MAP과 반대 방향(FE -> 서버) 매핑.
// schema.ts가 이미 "!="을 제외해뒀으므로(서버 enum에 없음) 이 Record는 5개 키로 완전하다.
const OPERATOR_TO_API: Record<SingleRuleValues["operator"], EndingRuleDraftItem["operator"]> = {
  ">=": "gte",
  "<=": "lte",
  "==": "eq",
  ">": "gt",
  "<": "lt",
};

function toApiSingleRule(rule: SingleRuleValues): EndingRuleDraftItem {
  return {
    kind: "rule",
    id: rule.id,
    statId: rule.statId,
    operator: OPERATOR_TO_API[rule.operator],
    threshold: rule.value,
    nextOp: rule.nextOp,
  };
}

// 그룹 내부(rules)는 schema.ts의 ruleGroupSchema가 이미 단일 규칙만 허용하도록 강제해뒀다(그룹 중첩 불가).
function toApiRuleListItem(item: RuleListItemValues): EndingRuleDraftItem | EndingRuleGroupDraftItem {
  if (item.kind === "group") {
    return { kind: "group", id: item.id, rules: item.rules.map(toApiSingleRule), nextOp: item.nextOp };
  }
  return toApiSingleRule(item);
}

// order는 서버 스키마에 별도 숫자 필드가 없다 — statRules 배열 인덱스 자체가 order다(US-091 패턴과 동일).
function toApiEnding(ending: EndingValues): EndingDraftItem {
  return {
    id: ending.id,
    name: ending.name,
    turnCountGate: ending.turnGate,
    judgmentPrompt: ending.judgePrompt,
    epilogue: ending.epilogue ?? null,
    hint: ending.hint ?? null,
    statRules: ending.statRules.map(toApiRuleListItem),
  };
}

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
function toApiStartingSetup(setup: StartingSetupValues): StartingSetupDraftItem {
  return {
    id: setup.id,
    name: setup.name,
    prologue: setup.prologue,
    openingMessage: setup.openingSituation ?? null,
    playguide: setup.playGuide ?? null,
    suggestedReplies: setup.suggestedReplies,
    statDefs: setup.stats.map(toApiStatDef),
    endings: setup.endings.map(toApiEnding),
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
