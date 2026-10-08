/** 휠 이벤트가 이만큼 끊겨야 다음 넘김을 받는다. 트랙패드 한 번 밀기와 그 뒤 관성은 짧은 간격으로 이어지는 이벤트
 * 줄기라, 줄기가 끝날 때까지 잠가 두어야 한 번 밀어 여러 쪽이 넘어가지 않는다. */
const WHEEL_QUIET_GAP_MS = 200;

export type WheelTurnState = { lastEventAt?: number };

export type WheelTurnEvent = {
  deltaX: number;
  deltaY: number;
  ctrlKey: boolean;
  /** `WheelEvent.timeStamp`(ms). */
  timeStamp: number;
};

/**
 * 휠 이벤트 하나를 넘김으로 줄인다 — 한 번 굴리거나 밀면 한 쪽이다. 잠긴 동안 온 이벤트도 잠금을 늘리므로 관성이 길게
 * 이어져도 넘김은 처음 한 번뿐이다. 빠르게 연달아 굴리면 그 사이가 끊기지 않아 한 쪽으로 합쳐진다.
 *
 * 세로 휠과 트랙패드 가로 밀기를 둘 다 받고 더 크게 움직인 축의 부호로 방향을 정한다(아래·오른쪽 = 다음 쪽). 크기는
 * 보지 않아 `deltaMode`(줄·쪽 단위)와 무관하다. `ctrlKey` 가 붙은 이벤트는 트랙패드 핀치나 Ctrl+휠 확대라 넘기지도
 * 잠그지도 않는다.
 */
export function reduceWheel(
  state: WheelTurnState,
  { deltaX, deltaY, ctrlKey, timeStamp }: WheelTurnEvent,
): { state: WheelTurnState; turn: -1 | 0 | 1 } {
  if (ctrlKey) return { state, turn: 0 };
  const delta = Math.abs(deltaX) >= Math.abs(deltaY) ? deltaX : deltaY;
  if (delta === 0) return { state, turn: 0 };
  const isLocked = state.lastEventAt !== undefined && timeStamp - state.lastEventAt < WHEEL_QUIET_GAP_MS;
  const nextState = { lastEventAt: timeStamp };
  if (isLocked) return { state: nextState, turn: 0 };
  return { state: nextState, turn: delta > 0 ? 1 : -1 };
}
