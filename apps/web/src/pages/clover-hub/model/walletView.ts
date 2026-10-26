import type { HubViewer } from "./hubViewer";
import type { PurchaseSection } from "./purchaseSection";

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

/** 비로그인 "내 클로버" 자리의 로그인 버튼 라벨. 상품 행이 로그인으로 이어지는 갈래(`guest`)일 때만 충전을 말한다 — 결제가
 * 꺼져 있거나 아직 모르면 로그인해도 충전할 수 없을 수 있어, 로그인으로 확실히 할 수 있는 일(잔액 보기)만 말한다. */
export function getGuestLoginLabel(section: PurchaseSection | undefined): string {
  return section === "guest" ? "로그인하고 충전하기" : "로그인하고 잔액 보기";
}

/** "확인 중"으로 끝난 결제가 풀렸는가 — 기준 잔액보다 지금 잔액이 늘었으면 결제사 확인(웹훅)이 지급한 것으로 보고 그
 * 안내를 거둔다. 계속 두면 이미 잔액에 반영된 결제를 기다리게 한다.
 *
 * 기준은 결과가 나온 때의 잔액(`atSettle`)이다. 결제창에서 돌아와 화면을 새로 열면 결과가 잔액보다 먼저 나와 그 값이
 * 없으므로, 그때는 그 뒤 처음 도착한 잔액(`firstArrived`)을 기준으로 삼는다 — 비워 두면 잔액이 늘어도 영원히 "확인 중"이다.
 * 기준도 지금 잔액도 없으면 그대로 둔다. */
export type CheckingBaseline = { atSettle: number | undefined; firstArrived: number | undefined };

export function isCheckingResolved(baseline: CheckingBaseline, balanceNow: number | undefined): boolean {
  const before = baseline.atSettle ?? baseline.firstArrived;
  return before !== undefined && balanceNow !== undefined && balanceNow > before;
}
