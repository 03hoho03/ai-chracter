/**
 * 필수 텍스트 칸이 비었는가 — 빈 문자열이거나 `String.prototype.trim()` 이 지우는 문자(공백·줄바꿈·탭·BOM 등)만인 값.
 * 서버 발행 검사도 같은 문자 집합으로 판정하므로 화면이 통과시킨 칸을 서버가 막거나 그 반대가 생기지 않는다. 판정만 하고
 * 값은 고치지 않는다 — 작가가 친 앞뒤 공백은 그대로 저장된다.
 */
export function isBlankText(value: string): boolean {
  return value.trim().length === 0;
}

/**
 * 필수 텍스트 칸 검사 — `z.string().refine(...requiredText("이름을 입력해주세요"))` 처럼 펼쳐 넣는다. `.min(1)` 은 공백만인
 * 값을 통과시키고, `.trim()` 변환은 저장값까지 잘라 버려서 쓰지 않는다.
 */
export function requiredText(message: string) {
  return [(value: string) => !isBlankText(value), message] as const;
}
