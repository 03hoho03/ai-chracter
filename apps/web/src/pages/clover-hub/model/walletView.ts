import type { HubViewer } from "./hubViewer";

/** "내 클로버" 자리에 무엇을 그릴지.
 *
 * - `pending` — 세션이나 잔액을 아직 묻는 중이다(스켈레톤).
 * - `guest` — 로그인하지 않았다. 잔액을 묻지 않고(물으면 401 이다) 로그인 안내를 둔다.
 * - `error` — 잔액을 받지 못했다. **0을 그리지 않는다** — 받지 못한 잔액을 0으로 보이면 충전한 사람이 잔액이 사라진
 *   것으로 읽는다. 재동의 전 403 도 여기로 온다(전역 재동의 모달이 위에 뜬다).
 * - `ready` — 받은 잔액. 다시 받기만 실패했으면 이미 받은 값을 그대로 보인다(30초 안전망 재조회 실패로 잔액을 지우지
 *   않는다). */
export type WalletView<Balance> =
  | { kind: "pending" }
  | { kind: "guest" }
  | { kind: "error" }
  | { kind: "ready"; balance: Balance };

export function getWalletView<Balance>(
  viewer: HubViewer,
  balance: { data: Balance | undefined; isError: boolean },
): WalletView<Balance> {
  if (viewer.kind === "pending") return { kind: "pending" };
  if (viewer.kind === "guest") return { kind: "guest" };
  if (balance.data !== undefined) return { kind: "ready", balance: balance.data };
  return balance.isError ? { kind: "error" } : { kind: "pending" };
}
