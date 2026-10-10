import { isCreatorPayoutUnavailableError, type CreatorPayoutResponse } from "@/entities/creator-payout";

/** 탈퇴 확인의 크리에이터 적립금 경고 끝에 무엇을 둘지 — 탈퇴하기 전에 남은 적립금을 받을 길이 있는가.
 *
 * - `request` — 확정 잔액이 0 보다 크고 최소 지급액보다 적다. 탈퇴 확인에서만 받는 신청이라 이 자리에 신청 버튼을 둔다.
 * - `registerInfo` — `request` 와 같은 잔액인데 지급 정보가 없거나 서버가 읽지 못한다. 정산 화면의 지급 정보로 보낸다.
 * - `goToPayout` — 잔액이 최소 지급액 이상이다. 일반 신청이라 정산 화면으로 보낸다.
 * - `afterReconsent` — 받을 잔액이 있지만 재동의 모달 안이다. 재동의 전에는 서버가 신청을 받지 않고 다른 화면으로 갈
 *   수도 없어, 동의하면 정산 화면에서 신청할 수 있다고만 말한다.
 * - `inProgress` — 이미 신청한 지급이 처리 중이다. 탈퇴해도 그 지급은 처리된다.
 * - `notOffered` — 지급을 받지 않는다(서버가 지급을 열지 않았거나 정산이 꺼졌다). 탈퇴하면 받을 수 없다.
 * - `unknown` — 정산 정보를 못 읽었다. 받을 길이 있는지 몰라 아무것도 말하지 않는다(경고 문장은 따로 뜬다).
 * - `none` — 승인된 적이 없거나 받을 확정 잔액이 없다.
 *
 * 정산이 꺼진 503 은 앞서 받은 응답이 남아 있어도 `notOffered` 다 — 꺼진 동안은 신청이 503 이다. */
export type WithdrawalPayoutAction =
  | { kind: "request"; balanceKrw: number }
  | { kind: "registerInfo"; balanceKrw: number }
  | { kind: "goToPayout"; balanceKrw: number }
  | { kind: "afterReconsent"; balanceKrw: number }
  | { kind: "inProgress" }
  | { kind: "notOffered" }
  | { kind: "unknown" }
  | { kind: "none" };

type WithdrawalPayoutActionInput = {
  payout:
    | Pick<
        CreatorPayoutResponse,
        "everApproved" | "balanceKrw" | "minimumPayoutKrw" | "payoutAvailable" | "payoutInfo" | "inProgressPayout"
      >
    | undefined;
  error: unknown;
  isBehindReconsent: boolean;
};

export function getWithdrawalPayoutAction({
  payout,
  error,
  isBehindReconsent,
}: WithdrawalPayoutActionInput): WithdrawalPayoutAction {
  if (isCreatorPayoutUnavailableError(error)) return { kind: "notOffered" };
  if (payout === undefined) return error ? { kind: "unknown" } : { kind: "none" };
  if (!payout.everApproved) return { kind: "none" };
  // 서버가 새 신청을 받지 않는 동안에도 이미 신청한 지급은 운영자가 끝까지 처리한다 — 받을 수 없다고 말하지 않는다.
  if (payout.inProgressPayout) return { kind: "inProgress" };
  if (!payout.payoutAvailable) return { kind: "notOffered" };
  const { balanceKrw } = payout;
  if (balanceKrw <= 0) return { kind: "none" };
  if (isBehindReconsent) return { kind: "afterReconsent", balanceKrw };
  if (balanceKrw >= payout.minimumPayoutKrw) return { kind: "goToPayout", balanceKrw };
  // 서버가 실명을 읽지 못하는 지급 정보로는 운영자도 이체할 수 없다 — 신청 대신 다시 입력받는다.
  if (payout.payoutInfo === null || payout.payoutInfo.maskedName === null) return { kind: "registerInfo", balanceKrw };
  return { kind: "request", balanceKrw };
}
