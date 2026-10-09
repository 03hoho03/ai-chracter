/**
 * 지운 항목을 되돌릴지의 판정. 지우고 되돌리기 전 사이에 새 항목을 추가하면 되살린 항목까지 더해 서버 상한을 넘을 수 있다 —
 * 초안 자동저장은 발행 검사를 거치지 않아 상한을 넘은 목록이 폼에 들어가면 서버가 저장을 통째로 거절하고 그 초안의 자동저장이
 * 전부 멈춘다. 그래서 되돌리기 전에 지금 목록으로 다시 판정한다.
 *
 * - `restore`: 그대로(또는 상한에 맞게 고친 값으로) 되살린다. 고쳤으면 `note` 가 그 사실을 알린다.
 * - `refuse`: 되살리지 않는다. `reason` 이 왜인지 알린다.
 */
export type RestoreDecision<T> = { kind: "restore"; item: T; note?: string } | { kind: "refuse"; reason: string };

/** 목록이 이미 `max` 개면 되돌리지 않는다(되살리면 `max + 1` 개가 된다). */
export function restoreUnderLimit<T>(count: number, item: T, max: number, reason: string): RestoreDecision<T> {
  return count >= max ? { kind: "refuse", reason } : { kind: "restore", item };
}
