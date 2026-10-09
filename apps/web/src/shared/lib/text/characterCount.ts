/**
 * 글자 수를 코드 포인트로 센다. 서버가 파이썬 `len()`(코드 포인트, 앞뒤 공백 포함)으로 한도를 재므로 화면도 같은
 * 단위로 센다 — `.length`(UTF-16)로 세면 이모지가 두 글자가 돼 서버가 받는 길이를 화면이 먼저 막는다. 결합 문자는
 * 서버처럼 따로 센다(`e` + 결합 악센트는 2).
 */
export function countCharacters(value: string): number {
  return [...value].length;
}

/**
 * 글자 수를 서버와 같은 코드 포인트로 잘라, 입력이 상한을 넘는 값을 폼에 만들지 않는다. 잘랐는지도 함께 돌려줘
 * 화면이 "넘친 글자는 넣지 않았어요" 를 그 순간에만 알릴 수 있게 한다(상한에 딱 맞는 입력은 자른 것이 아니다).
 */
export function clampCharacters(value: string, max: number): { value: string; isTruncated: boolean } {
  if (countCharacters(value) <= max) return { value, isTruncated: false };
  return { value: [...value].slice(0, max).join(""), isTruncated: true };
}
