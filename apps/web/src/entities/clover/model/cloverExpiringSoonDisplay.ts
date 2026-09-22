/** clover-page-goal-prompt.md CE-22 — 허브 페이지의 만료 임박 안내 문구.
 *
 * BE(`GET /me/clover`의 `expiringSoon`)가 이미 3일 임박 게이트와 "이미 만료된 로트 제외" 필터를
 * 걸어서 보낸다 — 이 함수는 그 값을 **다시 판정하지 않고** D-day 문구로만 바꾼다.
 *
 * 용어 "소멸"은 확정값이다(tasks/clover-page-progress.md U-3). "N일 뒤 소멸" 패턴을 그대로 쓴다.
 *
 * 일 수는 24시간 단위로 내림한다(`Math.floor`) — BE의 3일 임계값 자체도 달력 날짜가 아니라
 * `timedelta(days=3)` 원시 기간 산술이라(clover/router.py `EXPIRING_SOON_THRESHOLD`), 표시도
 * 같은 방식으로 맞춘다. 음수(이미 지난 시각)는 0으로 클램프한다 — BE 필터가 실전에서 이 입력을
 * 막지만, 순수 함수는 방어적으로 둔다. */
export function formatCloverExpiringSoonMessage(
  expiringSoon: { amount: number; expiresAt: string } | null,
  now: Date,
): string | null {
  if (!expiringSoon) return null;

  const dayMs = 24 * 60 * 60 * 1000;
  const diffMs = new Date(expiringSoon.expiresAt).getTime() - now.getTime();
  const daysLeft = Math.max(0, Math.floor(diffMs / dayMs));
  const dday = daysLeft === 0 ? "오늘" : `${daysLeft}일 뒤`;

  return `클로버 ${expiringSoon.amount.toLocaleString()}개가 ${dday} 소멸돼요`;
}
