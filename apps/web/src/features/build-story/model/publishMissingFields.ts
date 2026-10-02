import type { Path } from "react-hook-form";

import { MAX_MEDIA_BOOK_CELLS, type StoryBuilderFormValues } from "./schema";

// 서버(validate_story_publish)가 400으로 돌려주는 필드명을 한국어 라벨로 보여준다. 초안 상태를
// 표현하느라 nullable인 3필드(profile.image/registration.genre/target)도 이제는 폼
// 스키마의 refine이 먼저 막지만, 다른 기기에서 편집된 초안처럼
// 서버만 아는 상태가 남아 이 경로를 지우지 않는다.
// 키 집합은 validate_story_publish가 내는 **비인덱스** 필드 전부다(인덱스가 박힌
// `startingSetups[0].prologue` 류는 fallback 문구로 접힌다).
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
  // 엔딩 조건이 같은 시작설정에 없는 스탯을 가리킬 때 한 번 온다. 스탯을 지우면 그 조건도 함께 지워지고 자동저장도 같은
  // 조건을 먼저 거절하므로, 다른 기기에서 편집된 초안처럼 서버만 아는 상태에서만 닿는다.
  "endings.statRules": "엔딩 조건(지워진 스탯을 쓰는 조건)",
};

/** 서버 필드명의 단일 소스는 위 라벨 맵이다 — 아래 폼 경로 맵이 같은 키 집합을 덮는지 `satisfies`가
 * 검사한다. 어긋난 키는 fieldLabelByFormPath가 조용히 버려 토스트가 "그 밖의 필수 항목"으로 접히는데,
 * 두 맵을 손으로 맞추는 한 그 어긋남은 화면에서만 드러난다. */
type MissingField = keyof typeof STORY_MISSING_FIELD_LABELS;

/** 폼에 가리킬 자리가 없는 서버 필드. 인물·장면이 사라진 칸은 초안 응답이 이미 빼고 보내므로 화면에 그 칸이 없고,
 * 미디어 북을 한 번 다시 저장하면 서버에서도 지워진다 — 라벨로 알리기만 한다. */
type FieldWithoutFormPath = "mediaBook.orphanCells";

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
  // 노트 하나를 짚을 수 없어 배열 자리로 보낸다 — 키워드북 탭으로 이동하고 탭 머리 한 줄에 보인다.
  "keywordNotes.triggerKeywords": "keywordNotes",
  "keywordNotes.infoText": "keywordNotes",
  // 서버가 어느 시작설정인지 알려 주지 않는 키라 첫 시작설정의 엔딩 목록을 가리킨다 — 엔딩 탭으로 이동시키는 데만 쓴다.
  "endings.statRules": "startingSetups.0.endings",
} satisfies Record<Exclude<MissingField, FieldWithoutFormPath>, Path<StoryBuilderFormValues>>;
