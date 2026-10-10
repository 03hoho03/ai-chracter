import type { CreatorPayoutStatus } from "@/entities/creator-payout";

export type PayoutAction = "transfer" | "return" | "hold" | "replace-payee";

/**
 * 지급 건 상태·수취인 탈퇴 여부마다 걸 수 있는 처리. 상태·탈퇴 여부 판정은 서버와 같다.
 * - 처리 중 + 회원: 이체 기록·반려. 반려하면 금액이 잔액으로 돌아가 회원이 다시 신청한다.
 * - 처리 중 + 탈퇴: 이체 기록·보류·수취 정보 교체. 탈퇴한 회원은 다시 신청할 수 없어 반려하면 금액이 갈 곳을 잃는다 —
 *   반려 대신 보류하고 문의로 받은 정보로 수취인을 바꿔 이체한다.
 * - 보류(탈퇴한 회원만 생긴다): 이체 기록·수취 정보 교체.
 * - 지급 완료·반려: 끝난 건이라 없다.
 *
 * 수취 정보를 읽을 수 없으면(암호화 키 문제) 이체 기록을 빼고 나머지는 둔다. 이것은 화면만의 정책이다(서버의 이체 기록은
 * 읽기 가능 여부를 보지 않는다) — 누구에게 보냈는지 확인할 수 없는 이체를
 * 기록하지 않고, 회원은 반려 뒤 다시 입력해 재신청하며, 탈퇴 회원은 수취 정보를 바꾸면 다시 읽을 수 있다.
 */
export function availablePayoutActions(payout: {
  status: CreatorPayoutStatus;
  withdrawn: boolean;
  payeeInfoReadable: boolean;
}): PayoutAction[] {
  const actions = actionsByStatus(payout);
  return payout.payeeInfoReadable ? actions : actions.filter((action) => action !== "transfer");
}

function actionsByStatus({ status, withdrawn }: { status: CreatorPayoutStatus; withdrawn: boolean }): PayoutAction[] {
  switch (status) {
    case "requested":
      return withdrawn ? ["transfer", "hold", "replace-payee"] : ["transfer", "return"];
    case "held":
      return withdrawn ? ["transfer", "replace-payee"] : ["transfer"];
    case "paid":
    case "returned":
      return [];
  }
}
