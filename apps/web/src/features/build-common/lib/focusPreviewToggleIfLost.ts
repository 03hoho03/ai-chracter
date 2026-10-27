/** 상단바 [미리보기] 토글에 심는 표식(`BuilderTopBarActions` 가 같은 문자열을 리터럴로 심는다). */
const PREVIEW_TOGGLE_ATTRIBUTE = "data-builder-preview-toggle";

/**
 * 포커스를 쥔 요소가 화면에서 사라졌으면 상단바의 [미리보기] 토글로 옮긴다.
 *
 * lg 미만에서 묶음 줄의 테스트를 누르면 미리보기가 전체화면으로 서며 폼 열이 숨고, 누른 칸도 함께 숨어 포커스가 body 로
 * 떨어진다 — 다음 Tab 이 문서 처음부터 시작한다. 그 폭에서 보이는 토글은 지금 "미리보기 닫기"라 돌아갈 길이 그 자리에 있다.
 * 누른 칸이 그대로 보이는 넓은 화면에서는 아무것도 하지 않는다. 화면을 바꾼 뒤(`flushSync`) 불러야 숨음이 반영돼 있다.
 */
export function focusPreviewToggleIfLost(): void {
  const active = document.activeElement;
  if (active instanceof HTMLElement && active !== document.body && active.getClientRects().length > 0) return;
  document.querySelector<HTMLElement>(`[${PREVIEW_TOGGLE_ATTRIBUTE}]`)?.focus();
}
