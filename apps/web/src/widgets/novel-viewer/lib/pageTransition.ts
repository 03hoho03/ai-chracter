/** 쪽 넘김 전환 시간. 어느 쪽으로 갔는지 알리기에 충분하고, 연달아 넘길 때 기다리게 하지 않는 길이다. */
export const PAGE_TURN_MS = 250;

/**
 * 시스템 `ease-out`(`cubic-bezier(0, 0, 0.2, 1)`) 곡선의 진행률. 위·아래 바의 등장과 같은 곡선을 `scrollLeft` 에도
 * 쓰려고 직접 푼다 — 스크롤 위치는 CSS 전환으로 움직일 수 없다. 곡선의 x 는 매개변수에 대해 늘기만 해서 이분법으로
 * 매개변수를 찾는다.
 */
export function easeOut(progress: number): number {
  if (progress <= 0) return 0;
  if (progress >= 1) return 1;
  let low = 0;
  let high = 1;
  for (let step = 0; step < 24; step += 1) {
    const middle = (low + high) / 2;
    // 조절점 (0, 0)·(0.2, 1) 의 x(s) = 0.6s² + 0.4s³.
    if (0.6 * middle * middle + 0.4 * middle ** 3 < progress) low = middle;
    else high = middle;
  }
  const s = (low + high) / 2;
  // 같은 곡선의 y(s) = 3s² − 2s³.
  return 3 * s * s - 2 * s ** 3;
}
