/** 접기 머리 줄 토글에 심는 속성. 값은 그 항목의 열림 키다. */
export const ITEM_TOGGLE_ATTRIBUTE = "data-item-toggle";

function findItemToggle(openKey: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[${ITEM_TOGGLE_ATTRIBUTE}="${CSS.escape(openKey)}"]`);
}

/**
 * 열림 키로 그 항목의 머리 줄 토글에 포커스한다. 머리 줄은 접힘·펼침과 무관하게 늘 보이므로 삭제 뒤 포커스 목적지로
 * 쓸 수 있다. 토글이 없으면(다른 탭이거나 이미 사라짐) `false` 를 돌려 호출부가 다음 후보(추가 버튼)로 넘어가게 한다.
 */
export function focusItemToggle(openKey: string, options?: FocusOptions): boolean {
  const toggle = findItemToggle(openKey);
  if (!toggle) return false;
  toggle.focus(options);
  return true;
}

/** 열림 키로 그 항목의 머리 줄 토글이 스크롤 영역 안에 보이게 한다. 이미 보이면 움직이지 않는다(`block: "nearest"`). */
export function revealItemToggle(openKey: string): void {
  findItemToggle(openKey)?.scrollIntoView({ block: "nearest" });
}
