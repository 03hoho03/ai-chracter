import { pickFocusKeyAfterRemoval } from "../model/removalFocusKey";
import { focusItemToggle } from "./focusItemToggle";

/**
 * 항목을 지우기 **전에** 부른다. 다음 항목의 머리 줄 토글로, 없으면 이전 항목의 토글로, 그것도 없으면(하나뿐이었거나
 * 토글이 화면에 없으면) `fallback`(보통 목록의 추가 버튼)으로 포커스를 옮긴다. `keys` 는 지우기 전 목록 순서의 열림
 * 키다. 지운 뒤로 미루면 누른 삭제 버튼이 사라지며 포커스가 `<body>` 로 떨어진다.
 */
export function focusNeighborToggle(
  keys: readonly string[],
  removedIndex: number,
  fallback: HTMLElement | null | undefined,
): void {
  const target = pickFocusKeyAfterRemoval(keys, removedIndex);
  if (target === undefined || !focusItemToggle(target)) fallback?.focus();
}
