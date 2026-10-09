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

/**
 * 되돌리기로 되살린 항목의 머리 줄 토글로 포커스를 옮기고 그 머리 줄이 보이게 한다. 항목이 이미 DOM 에 커밋된 뒤(`flushSync`)
 * 부른다. 되돌리기 버튼에 포커스가 있으면 첫 이동이 토스트를 떠나는 순간 sonner 가 토스트에 들어오기 전 자리로 포커스를
 * 돌려보내고 그 자리를 잊는다 — 그래서 한 번 더 옮긴다. 버튼에 포커스가 없었으면(클릭이 포커스를 주지 않는 브라우저) 첫
 * 이동으로 끝나고 둘째는 아무것도 바꾸지 않는다.
 *
 * 포커스는 스크롤 없이 주고, 보이게 하는 일은 다음 프레임에 따로 한다. 지금 보이는 항목 위쪽에 카드를 끼워 넣으면 브라우저의
 * 스크롤 앵커링이 보이던 항목을 제자리에 두려고 카드 높이만큼 스크롤을 내려, 되살린 머리 줄이 화면 위로 밀려난다(포커스의
 * `preventScroll` 은 이것을 막지 않는다). 그 조정 뒤에 머리 줄만 화면 안으로 들인다 — 이미 보이면 움직이지 않고, 부드러운
 * 스크롤을 쓰지 않아 움직임 줄이기 설정과 상관없이 한 번에 옮긴다.
 */
export function focusRestoredToggle(openKey: string): void {
  if (focusItemToggle(openKey, { preventScroll: true })) focusItemToggle(openKey, { preventScroll: true });
  requestAnimationFrame(() => revealItemToggle(openKey));
}
