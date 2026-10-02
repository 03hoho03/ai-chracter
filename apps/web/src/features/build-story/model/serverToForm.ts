import type { components } from "@ai-character-chat/api-types";

import type { StoryDraftContent } from "@/entities/content";

import type {
  DevelopmentExampleValues,
  EndingValues,
  KeywordNoteValues,
  MediaBookCellValues,
  MediaBookValues,
  RuleListItemValues,
  SingleRuleValues,
  StartingSetupValues,
  StatDefValues,
  StoryBuilderFormValues,
} from "./schema";

type DevelopmentExampleItem = components["schemas"]["DevelopmentExampleItem"];
type StartingSetupDraftItem = components["schemas"]["StartingSetupDraftItem"];
type StatDefDraftItem = components["schemas"]["StatDefDraftItem"];
type KeywordNoteDraftItem = components["schemas"]["KeywordNoteDraftItem"];
type EndingDraftItem = components["schemas"]["EndingDraftItem"];
type EndingRuleDraftItem = components["schemas"]["EndingRuleDraftItem"];
type EndingRuleGroupDraftItem = components["schemas"]["EndingRuleGroupDraftItem"];
type MediaBookDraft = components["schemas"]["MediaBookDraft"];
type MediaBookCellDraftItem = components["schemas"]["MediaBookCellDraftItem"];

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
    perTurnDelta: stat.perTurnDelta ?? undefined,
  };
}

// 서버 계약(`DevelopmentExampleItem`)엔 id가 없다 — 필드명만 그대로 옮긴다.
function fromApiDevelopmentExample(dto: DevelopmentExampleItem): DevelopmentExampleValues {
  return { userLine: dto.userLine, assistantLine: dto.assistantLine };
}

// startingSetupId === null이면 global, 아니면 startingSetup 스코프로 역변환한다. 옵션 넷은 생성 타입에서 선택 필드라
// (서버는 늘 채워 보낸다) 빠지면 새 노트와 같은 기본값으로 채운다.
function fromApiKeywordNote(note: KeywordNoteDraftItem): KeywordNoteValues {
  return {
    id: note.id,
    content: note.infoText,
    triggerKeywords: note.triggerKeywords,
    scope:
      note.startingSetupId === null
        ? { kind: "global" }
        : { kind: "startingSetup", startingSetupId: note.startingSetupId },
    name: note.name ?? "",
    excludeKeywords: note.excludeKeywords ?? [],
    stickyTurns: note.stickyTurns ?? 0,
    alwaysOn: note.alwaysOn ?? false,
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

// 이미지 크기는 서버가 아직 재지 못한 자산(크기 기록 전에 올라온 것)이면 null 이다.
function fromApiMediaBookCell(cell: MediaBookCellDraftItem): MediaBookCellValues {
  return {
    id: cell.id,
    personId: cell.personId,
    sceneId: cell.sceneId,
    imageAssetId: cell.imageAssetId,
    imageUrl: cell.imageUrl,
    imageWidth: cell.imageWidth ?? undefined,
    imageHeight: cell.imageHeight ?? undefined,
    situationDescription: cell.situationDescription,
    unlockHint: cell.unlockHint,
    excludeFromChat: cell.excludeFromChat,
  };
}

// 응답의 `mediaBook`은 서버가 기본값을 둔 필드라 생성 타입에서 생략 가능하다 — 타입이 존재를 보장하지 않으므로
// 없으면 빈 미디어 북으로 받는다.
function fromApiMediaBook(mediaBook: MediaBookDraft | undefined): MediaBookValues {
  if (!mediaBook) return { people: [], scenes: [], cells: [] };
  return {
    people: mediaBook.people.map(({ id, name }) => ({ id, name })),
    scenes: mediaBook.scenes.map(({ id, name }) => ({ id, name })),
    cells: mediaBook.cells.map(fromApiMediaBookCell),
  };
}

/**
 * `GET /contents/{id}/draft` 응답 중 profile/storySetting/startingSetups/keywordNotes/shortcuts/
 * registration 부분 -> 폼 defaultValues(순수 함수).
 *
 * `settingText`/`customPrompt`는 promptTemplate 값과 무관하게 서버가 저장된 값을 그대로 돌려주므로
 * 여기서 분기 없이 그대로 복원한다 — 필수 여부 분기는 `schema.ts`의
 * `storySettingSchema` superRefine에서만 적용된다. `developmentExamples`/`userGoal`/`rules`도 같은
 * 이유로 분기 없이 그대로 복원한다(템플릿과 무관하게 항상 적용). 구
 * 필드 `developmentExample`은 더 이상 폼에서 관리하지 않는다(`formToServer.ts` 참고).
 *
 * endings가 startingSetups의 마지막 남은 필드였다 — 이제 전체 `StoryDraftResponse`를 그대로
 * 받으므로 예전에 쓰던 `Pick<...>` 좁히기가 더 필요 없다(`formToServer.ts`와 대칭).
 *
 * 받는 타입이 `StoryDraftResponse`가 아니라 id를 뺀 `StoryDraftContent`인 이유는 초안 지연 생성이다 — 아직
 * 서버에 없는 초안(`createEmptyDraft`)도 같은 함수로 폼 초기값을 만든다.
 */
export function serverToForm(data: StoryDraftContent): StoryBuilderFormValues {
  return {
    profile: {
      name: data.name,
      oneLiner: data.oneLiner,
      image: data.thumbnailAssetId ? { assetId: data.thumbnailAssetId } : null,
    },
    storySetting: {
      promptTemplate: data.promptTemplate,
      worldSetting: data.settingText ?? undefined,
      developmentExamples: data.developmentExamples.map(fromApiDevelopmentExample),
      userGoal: data.userGoal ?? undefined,
      rules: data.rules ?? undefined,
      customPrompt: data.customPrompt ?? undefined,
    },
    startingSetups: data.startingSetups.map(fromApiStartingSetup),
    keywordNotes: data.keywordNotes.map(fromApiKeywordNote),
    shortcuts: data.shortcuts,
    mediaBook: fromApiMediaBook(data.mediaBook),
    registration: {
      description: data.description,
      genre: data.genreId,
      target: data.target,
      hashtags: data.hashtags,
      visibility: data.visibility,
    },
  };
}
