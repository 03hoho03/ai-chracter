/**
 * 글자 수를 코드 포인트로 센다. 서버가 파이썬 `len()`(코드 포인트, 앞뒤 공백 포함)으로 한도를 재므로 화면도 같은
 * 단위로 센다 — `.length`(UTF-16)로 세면 이모지가 두 글자가 돼 서버가 받는 길이를 화면이 먼저 막는다. 결합 문자는
 * 서버처럼 따로 센다(`e` + 결합 악센트는 2).
 */
export function countCharacters(value: string): number {
  return [...value].length;
}

export type ClampedInput = {
  value: string;
  /** 자른 뒤 커서 자리(UTF-16 위치 — 입력칸의 `setSelectionRange` 가 받는 단위). */
  caret: number;
  isTruncated: boolean;
};

/**
 * 방금 입력을 반영한 칸의 값을 상한(코드 포인트)에 맞춘다. 넘친 만큼을 커서 바로 앞 — 방금 넣은 글 — 에서 덜어내므로
 * 꽉 찬 글 중간에 붙여넣어도 원래 있던 뒷부분은 지워지지 않는다(선택 영역을 덮어쓴 경우도 브라우저가 이미 바꿔 넣은
 * 뒤라 같다). 덜어내는 단위가 코드 포인트라 이모지를 반쪽으로 쪼개지 않는다. 커서 앞을 다 덜어도 넘치면(상한을 넘은
 * 채 저장된 글) 뒤에서 마저 자른다. 잘랐는지도 함께 돌려줘 화면이 그 순간에만 알릴 수 있게 한다.
 *
 * `caret` 은 입력 직후의 `selectionEnd`(UTF-16 위치)다.
 */
export function clampAtCaret(value: string, caret: number, max: number): ClampedInput {
  const boundary = isInsideSurrogatePair(value, caret) ? caret + 1 : caret;
  const before = [...value.slice(0, boundary)];
  const after = [...value.slice(boundary)];
  const overflow = before.length + after.length - max;
  if (overflow <= 0) return { value, caret, isTruncated: false };
  const keptBefore = before.slice(0, Math.max(0, before.length - overflow)).join("");
  const remaining = overflow - Math.min(overflow, before.length);
  const keptAfter = after.slice(0, after.length - remaining).join("");
  return { value: keptBefore + keptAfter, caret: keptBefore.length, isTruncated: true };
}

/** UTF-16 위치가 이모지 같은 서로게이트 쌍의 두 반쪽 사이인가. 그 자리에서 자르면 반쪽 글자가 남는다. */
function isInsideSurrogatePair(value: string, index: number): boolean {
  const high = value.charCodeAt(index - 1);
  const low = value.charCodeAt(index);
  return high >= 0xd800 && high <= 0xdbff && low >= 0xdc00 && low <= 0xdfff;
}
