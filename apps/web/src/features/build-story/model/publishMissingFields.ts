import type { Path } from "react-hook-form";

import { MAX_MEDIA_BOOK_CELLS, type StoryBuilderFormValues } from "./schema";

// 서버(validate_story_publish)가 400으로 돌려주는 필드명을 한국어 라벨로 보여준다. 초안 상태를
// 표현하느라 nullable인 3필드(profile.image/registration.genre/target)도 이제는 폼
// 스키마의 refine이 먼저 막지만, 다른 기기에서 편집된 초안처럼
// 서버만 아는 상태가 남아 이 경로를 지우지 않는다.
// 키 집합은 validate_story_publish가 내는 **비인덱스** 필드 전부다. 인덱스가 박힌 `startingSetups[0].prologue` 류는
// `storyMissingFieldFormPath` 가 폼 경로로 옮기고 발행 전 확인 목록이 칸 라벨 표(`STORY_FIELD_LABELS`)에서 이름을 찾는다.
// 목록 줄 이름으로 쓰는 것은 서버 키가 목록 자리만 가리킬 때(스탯 범위 등) 무엇이 틀렸는지 말하는 라벨뿐이다
// (`storyMissingFieldServerLabel`). 칸 하나를 짚는 키의 이름은 칸 라벨 표가 정한다.
export const STORY_MISSING_FIELD_LABELS = {
  name: "이름",
  oneLiner: "한줄소개",
  thumbnailAssetId: "대표 이미지",
  customPrompt: "커스텀 프롬프트",
  settingText: "스토리 설정/정보",
  startingSetups: "시작설정",
  description: "등록 설명",
  genreId: "장르",
  target: "타겟",
  // 미디어 북 두 키는 자동저장이 같은 조건을 먼저 거절하므로 정상 흐름에선 나오지 않는다 — 다른 기기에서 편집된
  // 초안처럼 서버만 아는 상태에서만 닿는다.
  "mediaBook.cells": `미디어 북 칸(${MAX_MEDIA_BOOK_CELLS}개 이하)`,
  "mediaBook.orphanCells": "미디어 북(인물·장면이 사라진 칸)",
  // 키워드북 두 키는 노트 수와 상관없이 한 번씩 온다. 어느 노트인지는 발행 전 폼 검증이 노트 자리에서 먼저 보여 주므로
  // 정상 흐름에선 정보가 공백뿐인 노트나 다른 기기에서 편집된 초안처럼 서버만 아는 상태에서만 닿는다.
  "keywordNotes.triggerKeywords": "키워드북 트리거 키워드(상시 적용이 아닌 노트마다 1개 이상)",
  "keywordNotes.infoText": "키워드북 정보",
  // 엔딩 조건이나 엔딩의 우선순위 스탯이 같은 시작설정에 없는 스탯을 가리킬 때 한 번 온다(서버가 둘에 같은 키를 쓴다). 스탯을
  // 지우면 그 조건은 함께 지워지고 우선순위 스탯은 비워지며 자동저장도 같은 상태를 먼저 거절하므로, 다른 기기에서 편집된 초안처럼
  // 서버만 아는 상태에서만 닿는다.
  "endings.statRules": "엔딩 조건·우선순위 스탯(지워진 스탯을 쓰는 칸)",
  // 스탯의 최소·최대·초기값이 어긋나면(최소 < 최대, 최소 ≤ 초기 ≤ 최대가 아니면) 스탯 수와 상관없이 한 번 온다. 폼 검증이 그
  // 칸에서 먼저 막고 초안 저장은 이 검사를 하지 않으므로, API 직접 호출이나 폼 검증 전에 저장된 초안처럼 서버만 아는 상태에서만 닿는다.
  "stats.range": "스탯 범위(최소값 < 최대값, 초기값은 그 사이)",
  // 규칙 세 키도 스탯 수와 상관없이 한 번씩 온다. 폼 검증이 그 스탯의 규칙 목록·규칙 칸·턴당 칸에서 먼저 막고 스탯 탭이 턴당
  // 자동 변화와 규칙을 서로 잠그므로, 다른 기기에서 편집된 초안처럼 서버만 아는 상태에서만 닿는다.
  "stats.rules": "규칙이 없는 스탯(턴당 자동 변화가 없는 스탯마다 규칙 1개 이상)",
  "stats.ruleDelta": "스탯 규칙의 증감(스탯 범위 폭 이하)",
  "stats.rulesWithCounter": "스탯 규칙(턴당 자동 변화와 함께 쓸 수 없어요)",
  // 상황 노트 세 키도 노트 수와 상관없이 한 번씩 온다. 발행 전 폼 검증이 앞의 둘을 그 노트 칸에서 먼저 막고, 지워진 스탯 조건은
  // 초안 저장이 먼저 거절하므로, 다른 기기에서 편집된 초안처럼 서버만 아는 상태에서만 닿는다.
  "situationNotes.emptyConditionRules": "상황 노트 조건(노트마다 1개 이상)",
  "situationNotes.infoText": "상황 노트 상황",
  "situationNotes.conditionRules": "상황 노트 조건(지워진 스탯을 쓰는 조건)",
};

/** 서버 필드명의 단일 소스는 위 라벨 맵이다 — 아래 폼 경로 맵이 같은 키 집합을 덮는지 `satisfies`가
 * 검사한다. 폼 경로가 빠진 키는 칸에 걸리지 못해 발행 전 확인 목록에 오르지 않는다. */
type MissingField = keyof typeof STORY_MISSING_FIELD_LABELS;

// 위 서버 필드명을 form.setError()가 받는 폼 경로로 옮긴다 — 값은
// tabs.ts(STORY_TABS)의 fields 프리픽스 아래에 들어간다(profile.*는
// profile 탭, registration.*는 registration 탭). 선언 타입이 string 인덱스인 것은 서버가 주는 임의
// 문자열로 조회하기 때문이고(인덱스 경로 포함), 키 커버리지는 아래 `satisfies`가 잠근다.
export const STORY_MISSING_FIELD_FORM_PATH: Partial<Record<string, Path<StoryBuilderFormValues>>> = {
  name: "profile.name",
  oneLiner: "profile.oneLiner",
  thumbnailAssetId: "profile.image",
  customPrompt: "storySetting.customPrompt",
  // 서버의 `settingText`가 폼에서는 `worldSetting`이다(formToServer.ts의 매핑).
  settingText: "storySetting.worldSetting",
  startingSetups: "startingSetups",
  description: "registration.description",
  genreId: "registration.genre",
  target: "registration.target",
  "mediaBook.cells": "mediaBook.cells",
  // 인물·장면이 사라진 칸은 초안 응답이 이미 빼고 보내 화면에 그 칸이 없다. 미디어 북을 한 번 다시 저장하면 서버에서도 지워지므로
  // 미디어 북 전체를 가리켜 그 탭으로 보낸다 — 미디어 북을 고치면(값이 바뀌면) 이 거절도 풀린다.
  "mediaBook.orphanCells": "mediaBook",
  // 노트 하나를 짚을 수 없어 배열 자리로 보낸다 — 키워드북 탭으로 이동하고 탭 머리 한 줄에 보인다.
  "keywordNotes.triggerKeywords": "keywordNotes",
  "keywordNotes.infoText": "keywordNotes",
  // 서버가 어느 시작설정인지 알려 주지 않는 키라 첫 시작설정의 엔딩 목록을 가리킨다 — 엔딩 탭으로 이동시키는 데만 쓴다.
  "endings.statRules": "startingSetups.0.endings",
  // 위와 같은 이유로 첫 시작설정의 스탯 목록을 가리킨다 — 스탯 탭으로 이동시키는 데만 쓴다.
  "stats.range": "startingSetups.0.stats",
  "stats.rules": "startingSetups.0.stats",
  "stats.ruleDelta": "startingSetups.0.stats",
  "stats.rulesWithCounter": "startingSetups.0.stats",
  // 셋 다 서버가 어느 노트인지 알려 주지 않는다. 폼에서 그 노트를 찾을 수 있으면 셸이 그 칸을 짚고(situationNoteErrors.ts),
  // 못 찾으면 이 경로로 첫 시작설정의 상황 노트 목록을 가리켜 상황 노트 탭으로 이동시킨다.
  "situationNotes.emptyConditionRules": "startingSetups.0.situationNotes",
  "situationNotes.infoText": "startingSetups.0.situationNotes",
  "situationNotes.conditionRules": "startingSetups.0.situationNotes",
} satisfies Record<MissingField, Path<StoryBuilderFormValues>>;

/** 서버가 인덱스를 박아 보내는 키(`startingSetups[1].prologue`, `startingSetups[0].endings[2].turnCountGate`)와 그 폼 경로. 클라 검사가
 * 같은 조건을 먼저 막아 정상 흐름에서는 닿지 않고, 다른 기기에서 고친 초안처럼 서버만 아는 상태에서 온다. */
const INDEXED_MISSING_FIELDS: readonly { pattern: RegExp; toFormPath: (match: RegExpExecArray) => string }[] = [
  {
    pattern: /^startingSetups\[(\d+)\]\.(name|prologue)$/,
    toFormPath: (match) => `startingSetups.${match[1]}.${match[2]}`,
  },
  {
    // 서버의 `turnCountGate` 가 폼에서는 `turnGate` 다(formToServer.ts 의 매핑).
    pattern: /^startingSetups\[(\d+)\]\.endings\[(\d+)\]\.turnCountGate$/,
    toFormPath: (match) => `startingSetups.${match[1]}.endings.${match[2]}.turnGate`,
  },
];

/** 서버 400 의 필드명을 `form.setError()` 가 받을 폼 경로로 옮긴다. 빌더가 모르는 키면 `undefined`. 순수 함수. */
export function storyMissingFieldFormPath(field: string): string | undefined {
  if (Object.hasOwn(STORY_MISSING_FIELD_FORM_PATH, field)) return STORY_MISSING_FIELD_FORM_PATH[field];
  for (const { pattern, toFormPath } of INDEXED_MISSING_FIELDS) {
    const match = pattern.exec(field);
    if (match) return toFormPath(match);
  }
  return undefined;
}

/** 칸 하나를 짚는 서버 키. 목록 줄 이름을 칸 라벨 표에서 찾아, 칸 라벨을 고치면 서버 400 줄도 같은 이름이 된다. */
const FIELD_KEYS: ReadonlySet<string> = new Set<MissingField>([
  "name",
  "oneLiner",
  "thumbnailAssetId",
  "customPrompt",
  "settingText",
  "startingSetups",
  "description",
  "genreId",
  "target",
]);

/**
 * 서버 400 의 목록 줄에 서버 쪽 라벨을 쓸 때 그 라벨. 순수 함수.
 *
 * 서버 키가 목록 자리만 가리키면(`stats.range` → 첫 시작설정의 스탯 목록) 칸 라벨로는 무엇이 틀렸는지 말할 수 없어 위 라벨을 준다.
 * 칸 하나를 짚는 키와 인덱스 키(`startingSetups[1].prologue`), 모르는 키는 `undefined` 라 호출부가 칸 라벨 표에서 찾는다.
 */
export function storyMissingFieldServerLabel(field: string): string | undefined {
  if (FIELD_KEYS.has(field)) return undefined;
  const labels: Readonly<Record<string, string | undefined>> = STORY_MISSING_FIELD_LABELS;
  return Object.hasOwn(labels, field) ? labels[field] : undefined;
}
