import type { components } from "@ai-character-chat/api-types";

import { defaultUserNameIssue } from "@/entities/persona";

import {
  mediaBookSchema,
  type DevelopmentExampleValues,
  type EndingValues,
  type KeywordNoteValues,
  type MediaBookCellValues,
  type MediaBookValues,
  type RuleListItemValues,
  type SingleRuleValues,
  type SituationNoteValues,
  type StartingSetupValues,
  type StatDefValues,
  type StoryBuilderFormValues,
} from "./schema";

type StoryDraftPayload = components["schemas"]["StoryDraftPayload"];
type DevelopmentExampleItem = components["schemas"]["DevelopmentExampleItem"];
type StartingSetupDraftItem = components["schemas"]["StartingSetupDraftItem"];
type StatDefDraftItem = components["schemas"]["StatDefDraftItem"];
type KeywordNoteDraftInput = components["schemas"]["KeywordNoteDraftInput"];
type EndingDraftItem = components["schemas"]["EndingDraftItem"];
type EndingRuleDraftItem = components["schemas"]["EndingRuleDraftItem"];
type EndingRuleGroupDraftItem = components["schemas"]["EndingRuleGroupDraftItem"];
type SituationNoteDraftItem = components["schemas"]["SituationNoteDraftItem"];
type MediaBookPayload = components["schemas"]["MediaBookPayload"];
type MediaBookCellInput = components["schemas"]["MediaBookCellInput"];

// endings가 startingSetups의 마지막 남은 필드였다 — 이제 storyBuilderSchema가 StoryDraftPayload의
// 모든 필드를 채우므로 예전에 쓰던 `Pick<...>` 좁히기가 더 필요 없다.
export type StoryBuilderDraftPayload = StoryDraftPayload;

// FE는 비교 연산자 기호(>=, <= ...)를 쓰고 서버는 EndingRuleOperator(gte/lte/eq/gt/lt,
// DB 컬럼 그대로)를 쓴다 — entities/chat-room/api/toChatRoomState.ts의 OPERATOR_MAP과 반대 방향(FE -> 서버) 매핑.
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

// order는 서버 스키마에 별도 숫자 필드가 없다 — statRules 배열 인덱스 자체가 order다(캐릭터 빌더와 같은 패턴).
function toApiEnding(ending: EndingValues): EndingDraftItem {
  return {
    id: ending.id,
    name: ending.name,
    turnCountGate: ending.turnGate,
    judgmentPrompt: ending.judgePrompt,
    epilogue: ending.epilogue ?? null,
    hint: ending.hint ?? null,
    statRules: ending.statRules.map(toApiRuleListItem),
    // 서버는 빠진 값을 "기존 값 유지"로 읽는다 — '없음'(null)도 보내야 비운 것이 저장된다.
    priorityStatId: ending.priorityStatId,
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
    perTurnDelta: stat.perTurnDelta ?? null,
    // 두 옵션은 기본값이어도 늘 보낸다 — 서버는 빠진 옵션을 "기존 값 유지"로 읽어(옵션을 모르는 옛 화면용), 빼면 기본값으로
    // 되돌린 것이 저장되지 않고 미리보기도 저장된 옵션 대신 기본값으로 돈다. 빈 폭 칸은 제한 없음(null)으로 보낸다.
    // 정수로 읽지 못한 폭 칸(NaN — 소수 붙여 넣기 등)만은 키를 뺀다: 정수가 아닌 값은 서버가 초안 저장째 거절하고, null 로
    // 보내면 작가가 걸어 둔 폭이 말없이 "제한 없음"으로 덮인다. 빼면 서버엔 마지막으로 저장된 폭이 남고, 칸의 잘못된 값은
    // 발행 때 폼 검증이 짚는다.
    changeDirection: stat.changeDirection,
    ...(Number.isNaN(stat.maxChangePerTurn) ? {} : { maxChangePerTurn: stat.maxChangePerTurn }),
  };
}

// 순서는 배열 위치다. 조건은 엔딩 규칙과 같은 서버 타입이다.
function toApiSituationNote(note: SituationNoteValues): SituationNoteDraftItem {
  return {
    id: note.id,
    name: note.name,
    infoText: note.content,
    conditionRules: note.conditionRules.map(toApiRuleListItem),
  };
}

// 서버 계약(`DevelopmentExampleItem`)엔 id가 없다 — 폼 쌍이 이미 그
// 모양이라 필드명만 그대로 옮긴다.
function toApiDevelopmentExample(item: DevelopmentExampleValues): DevelopmentExampleItem {
  return { userLine: item.userLine, assistantLine: item.assistantLine };
}

// scope.kind === 'global'이면 null, 아니면 참조한 시작설정 id로 변환한다. 옵션 넷(이름·금지 키워드·유지 턴·상시)은
// 기본값이어도 늘 보낸다 — 서버는 빠진 옵션을 "기존 값 유지"로 읽으므로(옵션을 모르는 옛 화면용) 빼면 이 화면에서
// 기본값으로 되돌린 것이 저장되지 않는다. 순서는 배열 위치다.
function toApiKeywordNote(note: KeywordNoteValues): KeywordNoteDraftInput {
  return {
    id: note.id,
    infoText: note.content,
    triggerKeywords: note.triggerKeywords,
    startingSetupId: note.scope.kind === "global" ? null : note.scope.startingSetupId,
    name: note.name,
    excludeKeywords: note.excludeKeywords,
    stickyTurns: note.stickyTurns,
    alwaysOn: note.alwaysOn,
  };
}

// order는 서버 스키마에 별도 숫자 필드가 없다 — 배열 인덱스 자체가 order다(캐릭터 빌더와 동일).
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
    // 빈 목록이어도 늘 보낸다 — 서버는 이 키가 없으면 그 시작설정의 노트를 그대로 두므로, 빼면 지운 노트·스탯 삭제로 함께
    // 지운 조건이 서버에 남는다.
    situationNotes: setup.situationNotes.map(toApiSituationNote),
  };
}

// `imageUrl`/`imageWidth`/`imageHeight`는 서버가 응답에서만 주는 표시용 값이라 싣지 않는다 — 서버 계약에
// 없는 필드는 서버가 조용히 버리지만, 보내지 않아야 페이로드가 계약 그대로 남는다.
function toApiMediaBookCell(cell: MediaBookCellValues): MediaBookCellInput {
  return {
    id: cell.id,
    personId: cell.personId,
    sceneId: cell.sceneId,
    imageAssetId: cell.imageAssetId,
    situationDescription: cell.situationDescription,
    unlockHint: cell.unlockHint,
    excludeFromChat: cell.excludeFromChat,
  };
}

// 폼이 미디어 북 전체를 들고 있으므로 보낼 때는 통째로 보낸다 — 서버는 보낸 목록에 없는 축·칸을 지운다.
function toApiMediaBook(mediaBook: MediaBookValues): MediaBookPayload {
  return {
    people: mediaBook.people.map(({ id, name }) => ({ id, name })),
    scenes: mediaBook.scenes.map(({ id, name }) => ({ id, name })),
    cells: mediaBook.cells.map(toApiMediaBookCell),
  };
}

/**
 * 폼값 -> `PATCH /contents/{id}/draft` payload 중 profile/storySetting/startingSetups/
 * keywordNotes/shortcuts/registration 부분(순수 함수).
 */
export function formToServer(values: StoryBuilderFormValues): StoryBuilderDraftPayload {
  return {
    name: values.profile.name,
    oneLiner: values.profile.oneLiner,
    thumbnailAssetId: values.profile.image?.assetId ?? null,
    promptTemplate: values.storySetting.promptTemplate,
    settingText: values.storySetting.worldSetting ?? null,
    // 구 컬럼(`developmentExample`)은 그 컬럼을 드롭하는 마이그레이션 전까지
    // 롤백 안전망으로 남아 있어야 한다. FE는 더 이상 이 필드를 폼에서 관리하지 않으므로 아예
    // 보내지 않는다 — BE가 "안 보냄"과 명시적 null을 구분해, 안 보내면 기존 값을 그대로 둔다.
    // 전개 예시의 출처는 이제 developmentExamples 하나뿐이다.
    developmentExamples: values.storySetting.developmentExamples.map(toApiDevelopmentExample),
    userGoal: values.storySetting.userGoal ?? null,
    // 서버는 이 칸이 없으면 저장된 값을 그대로 둔다. 입력 중간 상태(금지 문자 등)처럼 서버가 거절할 값을 실으면 PATCH 전체가
    // 422 가 돼 다른 칸의 수정까지 저장되지 않으므로, 그동안은 빼고 보낸다(칸 아래 오류가 그 사실을 알린다). 앞뒤 공백은 서버처럼
    // 걷어 보낸다 — 미리보기는 이 값을 그대로 이름으로 쓰므로, 걷지 않으면 미리보기 화면과 서버 프롬프트의 이름이 갈린다.
    ...(defaultUserNameIssue(values.storySetting.defaultUserName) === null
      ? { defaultUserName: values.storySetting.defaultUserName.trim() }
      : {}),
    rules: values.storySetting.rules ?? null,
    customPrompt: values.storySetting.customPrompt ?? null,
    startingSetups: values.startingSetups.map(toApiStartingSetup),
    keywordNotes: values.keywordNotes.map(toApiKeywordNote),
    shortcuts: values.shortcuts,
    // 서버는 `mediaBook` 이 없으면 미디어 북에 손대지 않는다. 입력 중간 상태(빈 이름 등)처럼 서버가 거절할
    // 미디어 북을 실으면 PATCH 전체가 422 가 돼 다른 탭의 수정까지 저장되지 않으므로, 그동안은 빼고 보낸다.
    ...(mediaBookSchema.safeParse(values.mediaBook).success ? { mediaBook: toApiMediaBook(values.mediaBook) } : {}),
    description: values.registration.description,
    genreId: values.registration.genre,
    target: values.registration.target,
    hashtags: values.registration.hashtags,
    visibility: values.registration.visibility,
  };
}
