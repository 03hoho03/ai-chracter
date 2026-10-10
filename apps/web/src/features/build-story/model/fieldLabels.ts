import {
  MAX_DEVELOPMENT_EXAMPLES,
  MAX_STARTING_SETUPS,
  MAX_SUGGESTED_REPLIES,
  NOVEL_PERMISSION_FIELD_LABEL,
} from "@/entities/content";

export type FieldLabel = {
  /** 별표 앞 글자 전부. 빌더가 별표 앞에 괄호를 그리는 칸(엔딩조건 (최소 턴수))은 괄호까지 여기에 둔다. */
  label: string;
  /** "conditional" 은 그리는 쪽이 값으로 정한다 — 트리거 키워드는 상시 적용이 꺼진 노트에서만 필수다. */
  required: boolean | "conditional";
  /** 별표 뒤 괄호 안 글. "시작설정 * (최대 4개)" 의 "최대 4개". */
  note?: string;
  /** 빌더가 그리는 입력 자리표시. 작성 가이드가 빈 칸으로 그리는 칸에만 둔다. */
  placeholder?: string;
};

/**
 * 스토리 빌더 칸 라벨의 단일 소스. 빌더 탭이 이 값으로 라벨과 필수 별표를 그리고, 작성 가이드의 빌더 모양 예시도 같은
 * 값을 읽어 두 화면의 칸 이름이 어긋날 수 없게 한다.
 *
 * 키는 폼 경로이고 배열 위치는 `*` 로 쓴다(`STORY_TABS` 의 `fields` 와 같은 표기). 폼 값이 없는 화면 칸은 `$` 로
 * 시작하는 조각을 쓴다(고급 설정 스위치). 목록 자체(`startingSetups` 등)도 키로 둔다.
 *
 * 빌더 화면에 라벨로 보이지 않는 키가 있다. 스탯 아이콘·색은 버튼의 접근 이름으로만 쓰이고, 전개 예시의 두 칸은 빌더에서
 * 자리표시로 보인다. 스탯·상황 노트·엔딩 목록과 미디어 북 인물·장면·배치표는 빌더에 같은 이름의 칸 라벨이 없어 작성 가이드만
 * 읽는다(탭 이름이나 배치표 머리와 같은 글자를 쓴다).
 */
export const STORY_FIELD_LABELS = {
  "profile.image": { label: "대표 이미지", required: true },
  "profile.name": { label: "이름", required: true },
  "profile.oneLiner": { label: "한줄소개", required: true },

  "storySetting.promptTemplate": { label: "프롬프트 템플릿", required: true },
  "storySetting.customPrompt": { label: "커스텀 프롬프트", required: true },
  "storySetting.worldSetting": { label: "스토리 설정/정보", required: true },
  "storySetting.rules": { label: "규칙", required: false },
  "storySetting.userGoal": { label: "사용자의 역할과 목표", required: false },
  "storySetting.developmentExamples": {
    label: "전개 예시",
    required: false,
    note: `고급 설정, 최대 ${MAX_DEVELOPMENT_EXAMPLES}개`,
  },
  "storySetting.developmentExamples.*.userLine": { label: "사용자 메시지", required: false },
  "storySetting.developmentExamples.*.assistantLine": { label: "스토리 응답", required: false },

  startingSetups: { label: "시작설정", required: true, note: `최대 ${MAX_STARTING_SETUPS}개` },
  "startingSetups.*.name": { label: "이름", required: true },
  "startingSetups.*.prologue": { label: "프롤로그", required: true },
  "startingSetups.*.openingSituation": { label: "시작상황", required: false },
  "startingSetups.*.$advanced": { label: "고급 설정", required: false },
  "startingSetups.*.playGuide": { label: "플레이가이드", required: false },
  "startingSetups.*.suggestedReplies": {
    label: "추천 답변",
    required: false,
    note: `최대 ${MAX_SUGGESTED_REPLIES}개`,
  },

  "startingSetups.*.stats": { label: "스탯", required: false },
  "startingSetups.*.stats.*.icon": { label: "아이콘", required: true },
  "startingSetups.*.stats.*.color": { label: "색", required: true },
  "startingSetups.*.stats.*.name": { label: "이름", required: true },
  "startingSetups.*.stats.*.min": { label: "최소값", required: true },
  "startingSetups.*.stats.*.max": { label: "최대값", required: true },
  "startingSetups.*.stats.*.initial": { label: "초기값", required: true },
  "startingSetups.*.stats.*.unit": { label: "단위", required: false },
  "startingSetups.*.stats.*.perTurnDelta": { label: "턴당 자동 변화", required: false },
  "startingSetups.*.stats.*.description": { label: "설명", required: true },
  "startingSetups.*.stats.*.rules": { label: "규칙", required: false },
  "startingSetups.*.stats.*.rules.*.condition": { label: "조건", required: true },
  "startingSetups.*.stats.*.rules.*.delta": { label: "증감", required: true },

  "startingSetups.*.situationNotes": { label: "상황 노트", required: false },
  "startingSetups.*.situationNotes.*.name": { label: "이름", required: false },
  "startingSetups.*.situationNotes.*.conditionRules": { label: "조건", required: true },
  "startingSetups.*.situationNotes.*.content": { label: "상황", required: true },

  mediaBook: { label: "미디어 북", required: false },
  "mediaBook.people": { label: "인물", required: false },
  "mediaBook.scenes": { label: "장면", required: false },
  "mediaBook.cells": { label: "배치표", required: false },
  "mediaBook.cells.*.situationDescription": { label: "상황 설명", required: false },
  "mediaBook.cells.*.unlockHint": { label: "해금 힌트", required: false },
  "mediaBook.cells.*.excludeFromChat": { label: "대화 중에는 띄우지 않기", required: false },

  keywordNotes: { label: "키워드북", required: false },
  "keywordNotes.*.name": { label: "이름", required: false },
  "keywordNotes.*.content": { label: "정보", required: true },
  "keywordNotes.*.triggerKeywords": { label: "트리거 키워드", required: "conditional" },
  "keywordNotes.*.excludeKeywords": {
    label: "금지 키워드",
    required: false,
    placeholder: "이 단어가 나온 턴엔 노트를 빼요",
  },
  "keywordNotes.*.stickyTurns": { label: "유지 턴", required: false },
  "keywordNotes.*.alwaysOn": { label: "상시 적용", required: false },
  "keywordNotes.*.scope": { label: "적용 대상", required: true },

  shortcuts: { label: "단축어", required: false },
  "shortcuts.*.name": { label: "이름", required: true },
  "shortcuts.*.description": { label: "설명", required: true },
  "shortcuts.*.prompt": { label: "실행될 프롬프트", required: true },

  "startingSetups.*.endings": { label: "엔딩", required: false },
  "startingSetups.*.endings.*.name": { label: "이름", required: true },
  "startingSetups.*.endings.*.turnGate": { label: "엔딩조건 (최소 턴수)", required: true },
  "startingSetups.*.endings.*.judgePrompt": { label: "판단 프롬프트", required: true },
  "startingSetups.*.endings.*.epilogue": { label: "에필로그", required: false },
  "startingSetups.*.endings.*.hint": { label: "엔딩힌트", required: false },
  "startingSetups.*.endings.*.statRules": { label: "스탯 기반 규칙", required: false, note: "선택" },
  "startingSetups.*.endings.*.priorityStatId": { label: "우선순위 스탯", required: false, note: "선택" },

  "registration.description": { label: "등록 설명", required: true },
  "registration.genre": { label: "장르", required: true },
  "registration.target": { label: "타겟", required: true },
  "registration.hashtags": { label: "해시태그", required: false },
  "registration.visibility": { label: "공개범위", required: true },
  "registration.novelPermission": { label: NOVEL_PERMISSION_FIELD_LABEL, required: false },
} as const satisfies Record<string, FieldLabel>;

export type StoryFieldKey = keyof typeof STORY_FIELD_LABELS;

/** 필수 여부를 그리는 쪽이 값으로 정하는 칸. */
export type ConditionalStoryFieldKey = {
  [Key in StoryFieldKey]: (typeof STORY_FIELD_LABELS)[Key]["required"] extends "conditional" ? Key : never;
}[StoryFieldKey];
