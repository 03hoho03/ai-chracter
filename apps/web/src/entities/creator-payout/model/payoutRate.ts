/** 서버가 주는 적립 비율(만분율, `rateBps`)을 화면 표기로 바꾼다(`500 → "5%"`, `750 → "7.5%"`). 소수는 반올림하지
 * 않고 그대로 보인다 — 비율을 깎아 말하면 정책과 어긋난다. */
export function formatPayoutRate(rateBps: number): string {
  return `${rateBps / 100}%`;
}
