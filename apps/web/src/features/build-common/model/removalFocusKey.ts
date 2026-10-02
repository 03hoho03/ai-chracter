/**
 * 항목을 지운 뒤 포커스를 옮길 항목의 열림 키. 다음 항목, 없으면 이전 항목이고, 하나뿐이었으면 `undefined` 라 호출부가
 * 목록의 추가 버튼으로 보낸다. `keys` 는 지우기 **전** 목록 순서다. 순수 함수.
 *
 * 다음·이전 항목의 머리 줄 토글은 지우기 전에도 화면에 있으므로 호출부는 지우기 전에 포커스를 옮기면 된다 — 지운 뒤로
 * 미루면 누른 삭제 버튼이 사라지며 포커스가 `<body>` 로 떨어진다.
 */
export function pickFocusKeyAfterRemoval(keys: readonly string[], removedIndex: number): string | undefined {
  return keys[removedIndex + 1] ?? keys[removedIndex - 1];
}
