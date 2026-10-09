import { clampAtCaret } from "@/shared/lib/text/characterCount";

type TextField = HTMLInputElement | HTMLTextAreaElement;

/**
 * 입력칸의 지금 값을 상한(코드 포인트)에 맞춰 자르고 커서를 방금 넣은 글 뒤로 되돌린다. 넘친 만큼은 방금 넣은 글에서
 * 덜어내 원래 있던 글은 지우지 않는다(`clampAtCaret`). 잘랐으면 true.
 */
export function clampFieldAtCaret(field: TextField, max: number): boolean {
  const result = clampAtCaret(field.value, field.selectionEnd ?? field.value.length, max);
  if (!result.isTruncated) return false;
  field.value = result.value;
  field.setSelectionRange(result.caret, result.caret);
  return true;
}

/**
 * 한글처럼 IME 가 글자를 조합하는 중의 입력인가. 조합 중에 값을 바꾸면 조합이 깨지므로 자르기는 조합이 끝난 뒤
 * (`compositionend`)로 미룬다. 브라우저마다 조합의 마지막 `input` 이 `compositionend` 앞(조합 중으로 표시)이기도 하고
 * 뒤(조합 끝으로 표시)이기도 해서, 두 자리 모두에서 자르고 자르기는 두 번 해도 결과가 같다.
 */
export function isComposingChange(event: { nativeEvent: Event }): boolean {
  return event.nativeEvent instanceof InputEvent && event.nativeEvent.isComposing;
}
