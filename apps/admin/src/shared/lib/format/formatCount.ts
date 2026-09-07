/** 어드민 목록·통계의 숫자 표기 — 천 단위 구분자를 넣는다. */
export function formatCount(value: number) {
  return value.toLocaleString("ko-KR");
}
