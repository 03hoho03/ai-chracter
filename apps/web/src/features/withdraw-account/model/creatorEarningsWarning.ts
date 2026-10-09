import { isCreatorPayoutUnavailableError, type CreatorPayoutResponse } from "@/entities/creator-payout";

/** 탈퇴 확인의 크리에이터 적립금 경고. 탈퇴하면 지급을 신청하지 않은 확정 잔액과 아직 확정되지 않은 적립이 모두
 * 사라지고(크리에이터 정산 정책의 탈퇴 조항), 지급 신청 기능이 아직 없어 탈퇴 전에 받을 방법도 없다.
 *
 * - `confirmed` — 승인된 적이 있고 확정 잔액이 0 보다 크다. 그 금액과 미확정 적립이 함께 사라진다.
 * - `unconfirmed` — 승인된 적이 있고 확정 잔액은 0 이하지만 미확정 적립이 있을 수 있다. 0 원이나 음수를 "확정된
 *   적립금이 사라진다"고 적지 않고, 있을 수 있는 미확정 적립만 말한다.
 * - `unavailable` — 정산이 꺼졌다(503). 꺼져도 탈퇴하면 적립은 그대로 사라지는데 꺼진 동안은 잔액을 읽을 수 없어,
 *   앞서 받아 둔 응답이 있어도 금액 없이 "있었다면" 조건으로만 말한다. 꺼지기 전 값은 그사이 확정이 돌았으면 틀린다.
 * - `unknown` — 정산이 켜져 있는데 적립 정보를 못 읽었다. 유료 클로버 경고와 같은 이유로 빼지 않고 숫자 없이 띄운다 —
 *   적립이 있는 작가가 경고 없이 떠나는 쪽이 비싸다.
 * - `none` — 세션상 정산이 꺼져 있거나(조회를 하지 않는다) 아직 읽는 중이거나 잃을 것이 없다. */
export type CreatorEarningsWarning =
  | { kind: "none" }
  | { kind: "confirmed"; balanceKrw: number }
  | { kind: "unconfirmed" }
  | { kind: "unavailable" }
  | { kind: "unknown" };

type CreatorEarningsWarningInput = {
  isPayoutEnabled: boolean;
  payout: Pick<CreatorPayoutResponse, "application" | "everApproved" | "balanceKrw"> | undefined;
  error: unknown;
  now: Date;
};

export function getCreatorEarningsWarning({ isPayoutEnabled, payout, error, now }: CreatorEarningsWarningInput): CreatorEarningsWarning {
  if (!isPayoutEnabled) return { kind: "none" };
  if (isCreatorPayoutUnavailableError(error)) return { kind: "unavailable" };
  if (payout === undefined) return error ? { kind: "unknown" } : { kind: "none" };
  if (!payout.everApproved) return { kind: "none" };
  if (payout.balanceKrw > 0) return { kind: "confirmed", balanceKrw: payout.balanceKrw };
  return mayHaveUnconfirmedEarnings(payout.application, now) ? { kind: "unconfirmed" } : { kind: "none" };
}

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;

/** 승인된 적이 있는 회원에게 아직 확정되지 않은 적립이 있을 수 있는가.
 *
 * 승인 중이면 언제나 그렇다. 승인 취소됐으면 취소한 달의 적립은 월 확정이 그 달을 확정할 수 있게 되는 다음 달 3일
 * 00:00(한국 시각)까지 남아 있다고 본다. 배치가 그보다 늦게 돌면 그 사이 몇 시간은 경고 없이 비어 있다. 그 뒤에 다시 신청해 대기·반려 중이면 응답이 가장 최근 신청만 담아 앞선 취소 시각을 알 수 없으므로 있다고 본다. */
function mayHaveUnconfirmedEarnings(application: CreatorPayoutResponse["application"], now: Date): boolean {
  if (application?.status !== "revoked" || application.revokedAt === null) return true;
  const revokedInKst = new Date(Date.parse(application.revokedAt) + KST_OFFSET_MS);
  const confirmedAt = Date.UTC(revokedInKst.getUTCFullYear(), revokedInKst.getUTCMonth() + 1, 3) - KST_OFFSET_MS;
  return now.getTime() < confirmedAt;
}
