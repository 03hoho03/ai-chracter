import {
  MAX_DESCRIPTION_LENGTH,
  MAX_HASHTAG_LENGTH,
  MAX_NAME_LENGTH,
  MAX_ONE_LINER_LENGTH,
} from "@/entities/content";
import {
  MAX_KEYWORD_NOTE_CONTENT_LENGTH,
  MAX_KEYWORD_NOTE_NAME_LENGTH,
  MAX_MEDIA_BOOK_NAME_LENGTH,
  MAX_MEDIA_BOOK_SITUATION_LENGTH,
  MAX_MEDIA_BOOK_UNLOCK_HINT_LENGTH,
  MAX_SITUATION_NOTE_CONTENT_LENGTH,
  MAX_SITUATION_NOTE_NAME_LENGTH,
  MAX_STAT_PLAYER_DESCRIPTION_LENGTH,
  MAX_STAT_RULE_CONDITION_LENGTH,
  MAX_STORY_SCENE_FIELD_LENGTH,
  MAX_TRIGGER_KEYWORD_LENGTH,
  type StoryFieldKey,
} from "@/features/build-story";

/**
 * 칸마다 AI가 그 글을 읽는 때. 개요 페이지의 그룹 목록(`title`)과 단계 페이지 목업 캡션(`caption`)이 이 표 하나에서
 * 나온다 — 같은 사실을 원고 산문과 코드 두 곳에 두면 한쪽만 고쳐지기 때문이다. 배열 순서가 개요에 보이는 순서다.
 *
 * `title` 은 예전 원고 개요 목록의 문장 그대로이고, `caption` 은 목업 캡션 한 줄(390px 폭에서 24자)에 들도록 줄인 말이다.
 * 원고 검사 밖의 글이라 마크다운 표기를 쓰지 않는다(평문으로 그린다).
 */
export const READ_TIMING_GROUPS = [
  { id: "everyTurn", title: "대화할 때마다 AI가 읽는다", caption: "대화마다 AI가 읽어요" },
  { id: "firstScreen", title: "첫 화면에 한 번 나오고, 그 뒤로는 지난 대화로 남는다", caption: "첫 화면에 한 번" },
  {
    id: "keyword",
    title: "사용자의 이번 메시지나 바로 앞 AI 응답에 그 단어가 나온 턴에 읽는다",
    caption: "키워드가 나온 턴에",
  },
  {
    id: "situationCondition",
    title: "사용자가 메시지를 보낸 순간의 스탯 값이 노트의 조건에 맞는 턴에 읽는다",
    caption: "조건이 맞는 턴에",
  },
  { id: "shortcut", title: "사용자가 단축어를 골랐을 때만 읽는다", caption: "단축어를 고를 때만" },
  { id: "judge", title: "점수와 엔딩을 판정할 때만 읽는다", caption: "판정할 때만" },
  { id: "imagePick", title: "대화 중 이미지를 고를 때만 읽는다", caption: "이미지 고를 때만" },
  { id: "notRead", title: "대화하는 AI는 읽지 않고 화면에만 보인다", caption: "대화 AI는 안 읽어요" },
] as const;

export type ReadTimingId = (typeof READ_TIMING_GROUPS)[number]["id"];

/**
 * 목업이 그리는 칸 모양. 원고의 값 본문을 어떻게 읽을지도 이것이 정한다(`model/mockupValue.ts`).
 * `group` 은 탭 전체를 가리키는 키(미디어 북)라 목업으로 그리지 않는다.
 */
export type MockupKind =
  | "text"
  | "textarea"
  | "chips"
  | "toggle"
  | "select"
  | "number"
  | "switch"
  | "statRules"
  | "statChangeRules"
  | "icon"
  | "color"
  | "image"
  | "cardList"
  | "mediaGrid"
  | "group";

export type FieldMockup = {
  kind: MockupKind;
  /** 튜토리얼 시드 JSON 에서 같은 칸의 경로(배열 위치는 `*`). 시드에 그 칸이 없거나 값이 비어 있으면 없다 — 예시 값을 free 로만 쓸 수 있다. */
  seedPath?: string;
  /** 없으면 원고가 그 칸을 AI가 언제 읽는지 말한 적이 없다는 뜻이라 캡션·개요 목록에 싣지 않는다(새 사실을 만들지 않는다). */
  readTiming?: ReadTimingId;
  /** 글자 수 상한. 빌더 스키마의 상수만 가리킨다 — 숫자를 여기 따로 적으면 스키마와 어긋날 수 있다. */
  limit?: number;
  /** 빌더가 `n/상한` 카운터를 그리는 칸. 목업도 같은 자리(입력칸 바로 아래 오른쪽)에 그린다. 칩 칸이면 입력칸에 쓰는
   * 항목 하나의 글자 수다. */
  counter?: true;
};

/**
 * 스토리 빌더 칸마다 작성 가이드 목업이 알아야 할 것. 키는 빌더 라벨 상수(`STORY_FIELD_LABELS`)와 같은 폼 경로이고,
 * 키 집합이 그 상수와 같아야 한다(빠지거나 남으면 타입 에러).
 */
export const STORY_FIELD_MOCKUPS = {
  "profile.image": { kind: "image", readTiming: "notRead" },
  "profile.name": { kind: "text", seedPath: "name", readTiming: "notRead", limit: MAX_NAME_LENGTH, counter: true },
  "profile.oneLiner": {
    kind: "text",
    seedPath: "oneLiner",
    readTiming: "notRead",
    limit: MAX_ONE_LINER_LENGTH,
    counter: true,
  },

  "storySetting.promptTemplate": { kind: "toggle", seedPath: "promptTemplate" },
  "storySetting.customPrompt": { kind: "textarea" },
  "storySetting.worldSetting": { kind: "textarea", seedPath: "settingText", readTiming: "everyTurn" },
  "storySetting.rules": { kind: "textarea", seedPath: "rules", readTiming: "everyTurn" },
  "storySetting.userGoal": { kind: "textarea", seedPath: "userGoal", readTiming: "everyTurn" },
  "storySetting.developmentExamples": {
    kind: "cardList",
    seedPath: "developmentExamples",
    readTiming: "everyTurn",
  },
  "storySetting.developmentExamples.*.userLine": {
    kind: "textarea",
    seedPath: "developmentExamples.*.userLine",
  },
  "storySetting.developmentExamples.*.assistantLine": {
    kind: "textarea",
    seedPath: "developmentExamples.*.assistantLine",
  },
  // 장면 헤더는 생성 AI 가 읽지 않는 화면 설정이다(첫 장면 두 칸도 같다). 튜토리얼 시드는 헤더를 켜고 첫 장면을 채운다.
  "storySetting.sceneHeaderEnabled": { kind: "switch", seedPath: "sceneHeaderEnabled" },

  startingSetups: { kind: "cardList", seedPath: "startingSetups" },
  "startingSetups.*.name": { kind: "text", seedPath: "startingSetups.*.name" },
  "startingSetups.*.prologue": { kind: "textarea", seedPath: "startingSetups.*.prologue", readTiming: "everyTurn" },
  "startingSetups.*.openingSituation": {
    kind: "textarea",
    seedPath: "startingSetups.*.openingMessage",
    readTiming: "firstScreen",
  },
  "startingSetups.*.initialScenePlace": {
    kind: "text",
    seedPath: "startingSetups.*.initialScenePlace",
    limit: MAX_STORY_SCENE_FIELD_LENGTH,
    counter: true,
  },
  "startingSetups.*.initialSceneTime": {
    kind: "text",
    seedPath: "startingSetups.*.initialSceneTime",
    limit: MAX_STORY_SCENE_FIELD_LENGTH,
    counter: true,
  },
  "startingSetups.*.$advanced": { kind: "switch" },
  "startingSetups.*.playGuide": { kind: "textarea", seedPath: "startingSetups.*.playguide", readTiming: "notRead" },
  // 목록은 화면에만 보이지만 누른 답변은 사용자 메시지로 AI에게 가서, 읽는 때 한 가지로 말할 수 없다.
  "startingSetups.*.suggestedReplies": {
    kind: "chips",
    seedPath: "startingSetups.*.suggestedReplies",
  },

  "startingSetups.*.stats": { kind: "cardList", seedPath: "startingSetups.*.statDefs" },
  "startingSetups.*.stats.*.icon": { kind: "icon", seedPath: "startingSetups.*.statDefs.*.icon" },
  "startingSetups.*.stats.*.color": { kind: "color", seedPath: "startingSetups.*.statDefs.*.color" },
  "startingSetups.*.stats.*.name": { kind: "text", seedPath: "startingSetups.*.statDefs.*.name" },
  "startingSetups.*.stats.*.min": { kind: "number", seedPath: "startingSetups.*.statDefs.*.minValue" },
  "startingSetups.*.stats.*.max": { kind: "number", seedPath: "startingSetups.*.statDefs.*.maxValue" },
  "startingSetups.*.stats.*.initial": {
    kind: "number",
    seedPath: "startingSetups.*.statDefs.*.initialValue",
  },
  // 시드의 단위는 모두 null 이라 인용할 글이 없다.
  "startingSetups.*.stats.*.unit": { kind: "text" },
  // 튜토리얼 시드의 스탯은 턴당 자동 변화를 쓰지 않는다 — 시계도 판정을 받는 스탯이다.
  "startingSetups.*.stats.*.perTurnDelta": { kind: "number" },
  "startingSetups.*.stats.*.description": {
    kind: "textarea",
    seedPath: "startingSetups.*.statDefs.*.description",
    readTiming: "judge",
  },
  // 숨김·플레이어용 설명·익명 신호는 AI가 읽지 않는 화면 설정이고 튜토리얼 시드도 쓰지 않는다.
  "startingSetups.*.stats.*.hiddenFromPlayer": { kind: "switch" },
  "startingSetups.*.stats.*.playerDescription": {
    kind: "text",
    limit: MAX_STAT_PLAYER_DESCRIPTION_LENGTH,
    counter: true,
  },
  "startingSetups.*.stats.*.signalHiddenChange": { kind: "switch" },
  "startingSetups.*.stats.*.rules": {
    kind: "statChangeRules",
    seedPath: "startingSetups.*.statDefs.*.rules",
    readTiming: "judge",
  },
  "startingSetups.*.stats.*.rules.*.condition": {
    kind: "textarea",
    seedPath: "startingSetups.*.statDefs.*.rules.*.condition",
    limit: MAX_STAT_RULE_CONDITION_LENGTH,
    counter: true,
  },
  "startingSetups.*.stats.*.rules.*.delta": {
    kind: "number",
    seedPath: "startingSetups.*.statDefs.*.rules.*.delta",
  },

  "startingSetups.*.situationNotes": { kind: "cardList", seedPath: "startingSetups.*.situationNotes" },
  "startingSetups.*.situationNotes.*.name": {
    kind: "text",
    seedPath: "startingSetups.*.situationNotes.*.name",
    limit: MAX_SITUATION_NOTE_NAME_LENGTH,
    counter: true,
  },
  "startingSetups.*.situationNotes.*.conditionRules": {
    kind: "statRules",
    seedPath: "startingSetups.*.situationNotes.*.conditionRules",
  },
  "startingSetups.*.situationNotes.*.content": {
    kind: "textarea",
    seedPath: "startingSetups.*.situationNotes.*.infoText",
    readTiming: "situationCondition",
    limit: MAX_SITUATION_NOTE_CONTENT_LENGTH,
    counter: true,
  },

  // 튜토리얼 시드에는 미디어 북이 없다 — 이 탭의 예시는 모두 free 다.
  mediaBook: { kind: "group" },
  "mediaBook.people": { kind: "chips", readTiming: "imagePick", limit: MAX_MEDIA_BOOK_NAME_LENGTH },
  "mediaBook.scenes": { kind: "chips", readTiming: "imagePick", limit: MAX_MEDIA_BOOK_NAME_LENGTH },
  "mediaBook.cells": { kind: "mediaGrid" },
  "mediaBook.cells.*.situationDescription": {
    kind: "textarea",
    readTiming: "imagePick",
    limit: MAX_MEDIA_BOOK_SITUATION_LENGTH,
    counter: true,
  },
  "mediaBook.cells.*.unlockHint": {
    kind: "text",
    readTiming: "notRead",
    limit: MAX_MEDIA_BOOK_UNLOCK_HINT_LENGTH,
    counter: true,
  },
  "mediaBook.cells.*.excludeFromChat": { kind: "switch" },

  keywordNotes: { kind: "cardList", seedPath: "keywordNotes" },
  "keywordNotes.*.name": {
    kind: "text",
    seedPath: "keywordNotes.*.name",
    limit: MAX_KEYWORD_NOTE_NAME_LENGTH,
    counter: true,
  },
  "keywordNotes.*.content": {
    kind: "textarea",
    seedPath: "keywordNotes.*.infoText",
    readTiming: "keyword",
    limit: MAX_KEYWORD_NOTE_CONTENT_LENGTH,
    counter: true,
  },
  "keywordNotes.*.triggerKeywords": {
    kind: "chips",
    seedPath: "keywordNotes.*.triggerKeywords",
    limit: MAX_TRIGGER_KEYWORD_LENGTH,
    counter: true,
  },
  // 금지 키워드는 트리거 키워드와 같은 길이 규칙을 쓴다(빌더 스키마가 같은 목록 스키마를 공유한다).
  "keywordNotes.*.excludeKeywords": {
    kind: "chips",
    limit: MAX_TRIGGER_KEYWORD_LENGTH,
    counter: true,
  },
  "keywordNotes.*.stickyTurns": { kind: "select" },
  "keywordNotes.*.alwaysOn": { kind: "switch" },
  // 시드의 `startingSetupId` 가 null 이면 빌더의 "스토리 전체"다.
  "keywordNotes.*.scope": { kind: "toggle", seedPath: "keywordNotes.*.startingSetupId" },

  shortcuts: { kind: "cardList", seedPath: "shortcuts" },
  "shortcuts.*.name": { kind: "text", seedPath: "shortcuts.*.name" },
  "shortcuts.*.description": { kind: "text", seedPath: "shortcuts.*.description" },
  "shortcuts.*.prompt": { kind: "textarea", seedPath: "shortcuts.*.prompt", readTiming: "shortcut" },

  "startingSetups.*.endings": { kind: "cardList", seedPath: "startingSetups.*.endings" },
  "startingSetups.*.endings.*.name": { kind: "text", seedPath: "startingSetups.*.endings.*.name" },
  "startingSetups.*.endings.*.turnGate": {
    kind: "number",
    seedPath: "startingSetups.*.endings.*.turnCountGate",
  },
  "startingSetups.*.endings.*.judgePrompt": {
    kind: "textarea",
    seedPath: "startingSetups.*.endings.*.judgmentPrompt",
    readTiming: "judge",
  },
  "startingSetups.*.endings.*.epilogue": {
    kind: "textarea",
    seedPath: "startingSetups.*.endings.*.epilogue",
    readTiming: "notRead",
  },
  "startingSetups.*.endings.*.hint": { kind: "text", seedPath: "startingSetups.*.endings.*.hint", readTiming: "notRead" },
  "startingSetups.*.endings.*.statRules": {
    kind: "statRules",
    seedPath: "startingSetups.*.endings.*.statRules",
  },
  // 시드는 우선 스탯을 이름(`priorityStat`)으로 적는다 — 로더가 id 로 바꾼다.
  "startingSetups.*.endings.*.priorityStatId": {
    kind: "select",
    seedPath: "startingSetups.*.endings.*.priorityStat",
  },

  "registration.description": {
    kind: "textarea",
    seedPath: "description",
    readTiming: "notRead",
    limit: MAX_DESCRIPTION_LENGTH,
    counter: true,
  },
  "registration.genre": { kind: "select", seedPath: "genreId", readTiming: "notRead" },
  "registration.target": { kind: "toggle", seedPath: "target", readTiming: "notRead" },
  "registration.hashtags": {
    kind: "chips",
    seedPath: "hashtags",
    readTiming: "notRead",
    limit: MAX_HASHTAG_LENGTH,
    counter: true,
  },
  "registration.visibility": { kind: "toggle", seedPath: "visibility", readTiming: "notRead" },
  "registration.novelPermission": { kind: "toggle" },
} as const satisfies Record<StoryFieldKey, FieldMockup>;

export type StoryFieldMockups = Readonly<Record<StoryFieldKey, FieldMockup>>;
