/** 글자 코드 순 비교 — 정렬 결과가 실행 환경의 언어 설정에 따라 달라지지 않는다. */
export function compareText(a: string, b: string): number {
  if (a < b) return -1;
  return a > b ? 1 : 0;
}
