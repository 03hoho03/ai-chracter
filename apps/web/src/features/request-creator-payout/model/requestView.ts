import type { CreatorPayoutResponse } from "@/entities/creator-payout";

/** 정산 화면의 지급 신청 자리에 무엇을 둘지. 위에서부터 먼저 맞는 갈래다.
 *
 * - `inProgress` — 처리 중인 지급이 있다. 끝날 때까지 새로 신청할 수 없다(잔액이 그사이 다시 쌓여도).
 * - `nothingToPay` — 확정 잔액이 0 이하다.
 * - `belowMinimum` — 잔액이 최소 지급액보다 적다. 버튼 대신 최소액을 말한다(최소액 미만 신청은 탈퇴 확인에서만 받는다).
 * - `infoRequired` — 지급 정보를 등록하지 않았다.
 * - `infoUnreadable` — 등록한 지급 정보를 서버가 읽지 못한다(암호화 키를 잃었다). 운영자도 이체할 수 없으니 다시
 *   입력받기 전에는 신청 버튼을 두지 않는다.
 * - `ready` — 확정 잔액 전액을 신청할 수 있다. 금액을 고르지 않는다. */
export type RequestView =
  | { kind: "inProgress"; amountKrw: number; requestedAt: string }
  | { kind: "nothingToPay" }
  | { kind: "belowMinimum"; minimumKrw: number }
  | { kind: "infoRequired" }
  | { kind: "infoUnreadable" }
  | { kind: "ready"; amountKrw: number };

export type RequestViewInput = Pick<
  CreatorPayoutResponse,
  "balanceKrw" | "minimumPayoutKrw" | "payoutInfo" | "inProgressPayout"
>;

export function getRequestView(payout: RequestViewInput): RequestView {
  if (payout.inProgressPayout) {
    return { kind: "inProgress", ...payout.inProgressPayout };
  }
  if (payout.balanceKrw <= 0) return { kind: "nothingToPay" };
  if (payout.balanceKrw < payout.minimumPayoutKrw) return { kind: "belowMinimum", minimumKrw: payout.minimumPayoutKrw };
  if (payout.payoutInfo === null) return { kind: "infoRequired" };
  if (payout.payoutInfo.maskedName === null) return { kind: "infoUnreadable" };
  return { kind: "ready", amountKrw: payout.balanceKrw };
}
