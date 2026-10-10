import type { CreatorPayoutResponse } from "@/entities/creator-payout";

type PayoutSectionsInput = Pick<CreatorPayoutResponse, "everApproved" | "payoutAvailable" | "inProgressPayout">;

/** 정산 화면에서 지급 쪽 자리 중 무엇을 보일지.
 *
 * 승인된 적이 없으면 셀 것이 없어 아무것도 없다. 지급 내역은 승인된 적만 있으면 보인다 — 서버가 새 신청을 받지 않는
 * 동안(`payoutAvailable` 거짓)에도 이미 신청한 지급은 운영자가 끝까지 처리하고, 내역 조회는 그 동안에도 된다. 신청과
 * 지급 정보 입력은 서버가 받을 때만 둔다. */
export function getPayoutSections({ everApproved, payoutAvailable }: PayoutSectionsInput) {
  return {
    request: everApproved && payoutAvailable,
    payoutInfo: everApproved && payoutAvailable,
    payouts: everApproved,
  };
}

/** 적립금 아래의 지급 안내 한 줄. 서버가 새 신청을 받지 않는 동안 처리 중인 지급이 있으면 "준비 중"이라고 하지 않는다 —
 * 그 지급은 이체된다. */
export function getBalancePayoutNote({ payoutAvailable, inProgressPayout }: PayoutSectionsInput): string {
  if (payoutAvailable) return "탈퇴하면 지급을 신청하지 않은 적립금은 사라져요.";
  if (inProgressPayout) {
    return "신청한 지급은 처리하고 있어요. 새 지급 신청은 지금 받지 않아요. 탈퇴하면 신청하지 않은 적립금은 사라져요.";
  }
  return "지급 신청은 준비 중이에요. 탈퇴하면 확정된 적립금도 사라져요.";
}
