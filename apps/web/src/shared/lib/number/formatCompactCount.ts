// 로케일을 "en"으로 고정한다 — "ko"는 `1.2천`·`4.7만`을 내는데, 이 앱이 고른 표기는 `46.8K`·`1.2M`이고
// 참조한 레퍼런스(크랙)도 K/M을 쓴다. 로케일을 생략하면 브라우저 설정에 따라 표기가 갈린다.
const COMPACT_COUNT_FORMATTER = new Intl.NumberFormat("en", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** 목록 카드의 지표 숫자(조회수·대화수·좋아요)를 축약 표기로 바꾼다(`46821 → "46.8K"`). 좁은 카드 폭에서
 * 자릿수가 늘수록 옆 텍스트(작가명)를 잠식하는 문제의 처방이다 — 상세화면(`ContentDetailView`)은 폭
 * 제약이 없어 전체 숫자(`toLocaleString()`)를 그대로 쓰고 이 포맷터를 쓰지 않는다. */
export function formatCompactCount(count: number): string {
  return COMPACT_COUNT_FORMATTER.format(count);
}
