/**
 * 화면 단축키가 이 키 입력을 받지 말아야 하는가 — 다른 처리기가 이미 막았거나, 입력기 조합 중이거나, 보조키를 쥐었거나(브라우저·
 * 운영체제 단축키), 글을 쓰는 칸에서 눌렀다. 목록·상세가 같은 판정을 써야 한 화면에서 되는 키가 다른 화면에서 글자를 먹지 않는다.
 */
export function isShortcutBlocked(event: KeyboardEvent): boolean {
  if (event.defaultPrevented || event.isComposing || event.metaKey || event.ctrlKey || event.altKey) return true;
  return isTypingTarget(event.target);
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}
