import {
  KEYWORD_NOTE_SCOPE_LABELS,
  PROMPT_TEMPLATE_LABELS,
  STICKY_TURN_OPTIONS,
  TARGET_LABELS,
  VISIBILITY_LABELS,
  type StoryFieldKey,
} from "@/features/build-story";

export type MockupChoice = { label: string; isSelected: boolean };

/**
 * 하나를 고르는 칸(칩 묶음)의 선택지와 원고 값이 고른 것. 선택지 글자는 빌더 탭이 읽는 상수 그대로라 빌더에서 선택지가
 * 바뀌면 그림도 같이 바뀐다. 원고 값은 시드 표기(템플릿·타겟·공개범위의 값 이름, 적용 대상은 시작설정 id 또는 null)다.
 */
export function choicesOf(key: StoryFieldKey, value: string | number | null): MockupChoice[] {
  switch (key) {
    case "storySetting.promptTemplate":
      return labelChoices(Object.entries(PROMPT_TEMPLATE_LABELS).map(([id, { label }]) => [id, label]), value);
    case "registration.target":
      return labelChoices(Object.entries(TARGET_LABELS), value);
    case "registration.visibility":
      return labelChoices(Object.entries(VISIBILITY_LABELS), value);
    case "keywordNotes.*.scope":
      // 시드는 적용 대상을 시작설정 id 로 적고, 비어 있으면(null) 빌더의 "스토리 전체"다.
      return labelChoices(Object.entries(KEYWORD_NOTE_SCOPE_LABELS), value === null ? "global" : "startingSetup");
    default:
      throw new Error(`선택지를 모르는 칸: ${key}`);
  }
}

/** 셀렉트 칸에 보이는 글. 유지 턴은 빌더 선택지 글자로, 장르는 목록이 서버에서 오므로 원고 값 그대로 보인다. */
export function selectLabelOf(key: StoryFieldKey, value: string | number | null): string {
  if (key === "keywordNotes.*.stickyTurns") {
    const option = STICKY_TURN_OPTIONS.find((candidate) => candidate.value === String(value));
    if (!option) throw new Error(`유지 턴 선택지에 없는 값: ${String(value)}`);
    return option.label;
  }
  return value === null ? "" : String(value);
}

function labelChoices(entries: readonly (readonly [string, string])[], value: string | number | null): MockupChoice[] {
  return entries.map(([id, label]) => ({ label, isSelected: id === value }));
}
