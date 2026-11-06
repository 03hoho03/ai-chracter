import type { SwitchGroup } from "../model/switchCopy";

/** 행의 `이력` 링크가 URL 조각(`#history`)으로도 가리키는 이력 제목. */
export const HISTORY_HEADING_ID = "history";
export const UNKNOWN_OVERRIDES_HEADING_ID = "feature-switch-unknown-overrides";

export function groupHeadingId(group: SwitchGroup) {
  return `feature-switch-group-${group}`;
}

/** 행의 스위치 이름 제목 — 「롤백 전에」 상자의 이름 링크가 여기로 포커스를 옮긴다. */
export function switchHeadingId(name: string) {
  return `feature-switch-${name}`;
}

/** 행의 켜기·끄기 버튼 — 덮어쓰기를 지운 뒤 포커스가 돌아갈 곳이다(지운 버튼은 사라진다). */
export function toggleButtonId(name: string) {
  return `feature-switch-${name}-toggle`;
}
