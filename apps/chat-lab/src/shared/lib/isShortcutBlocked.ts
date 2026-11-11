/**
 * 화면 단축키가 이 키 입력을 받지 말아야 하는가 — 다른 처리기가 이미 막았거나, 입력기 조합 중이거나, 보조키를 쥐었거나(브라우저·
 * 운영체제 단축키), 글을 쓰는 칸에서 눌렀거나, 모달 대화가 떠 있다. 목록·상세가 같은 판정을 써야 한 화면에서 되는 키가 다른 화면에서
 * 글자를 먹지 않는다. 모달 대화가 떠 있으면 가려진 화면의 단축키는 쉰다 — 대화 안의 Enter·Esc 가 뒤 화면의 행 열기·펼침 닫기로
 * 새거나 j/k 가 가려진 행·턴을 옮기지 않게.
 */
export function isShortcutBlocked(event: KeyboardEvent): boolean {
  if (event.defaultPrevented || event.isComposing || event.metaKey || event.ctrlKey || event.altKey) return true;
  if (document.querySelector("dialog:modal") !== null) return true;
  return isTypingTarget(event.target);
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}
