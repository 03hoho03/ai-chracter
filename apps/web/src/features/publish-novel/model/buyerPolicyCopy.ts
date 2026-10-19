/** 공개를 거두거나 운영 조치로 내려졌을 때 소장한 회원에게 무슨 일이 생기는지 게시자에게 말하는 문장. 노벨 정책
 * 스위치(가격 응답의 `novelPublicPolicyV2Enabled`)에 따라 사실이 다르다.
 *
 * - 꺼짐: 거두면 소장한 회원도 못 보고, 다시 공개하면 소장한 화가 다시 열린다.
 * - 켜짐: 거둬도 소장한 회원은 산 화를 계속 읽고 새로 소장만 막힌다. 운영 이용제한은 소장한 회원의 클로버를 돌려준다.
 *
 * 값이 없으면(옛 서버·가격 응답을 아직 못 받음) 꺼짐 문장이다 — 스위치가 켜지기 전의 지금 문장과 같다. */
export type BuyerPolicyCopy = {
  /** 거두기 확인 모달의 설명. */
  withdrawConfirm: string;
  /** 거둔 소설의 공개 절 첫 줄. */
  withdrawnStatus: string;
  /** 거둔 소설을 다시 공개할 수 있을 때의 둘째 줄. */
  withdrawnReopen: string;
  /** 공개 모달 아래 거두기 안내. */
  publishWithdrawNote: string;
  /** 운영 이용제한으로 내려진 소설의 공개 절 첫 줄. */
  restrictedStatus: string;
  /** 운영자가 판매를 멈춘 소설의 공개 절 첫 줄. 판매 중단은 스위치가 켜졌을 때만 걸 수 있어 문장은 하나지만, 켰다 끈
   * 뒤에도 남을 수 있어 꺼짐에도 같은 값을 둔다. */
  salesStoppedStatus: string;
};

const SALES_STOPPED_STATUS =
  "운영 정책에 따라 판매가 멈췄어요. 노벨 목록에 보이지 않고 새로 소장할 수 없어요. 이미 소장한 회원은 계속 읽어요.";

const OFF: BuyerPolicyCopy = {
  withdrawConfirm:
    "목록과 작품 화면에서 바로 사라지고, 소장한 회원도 더 볼 수 없게 돼요. 클로버는 돌려드리지 않아요. 나중에 다시 공개하면 소장한 화도 다시 열려요.",
  withdrawnStatus: "공개를 거둔 소설이에요. 노벨에 보이지 않고, 소장한 회원도 지금은 볼 수 없어요.",
  withdrawnReopen: "다시 공개하면 소장한 화도 다시 열려요.",
  publishWithdrawNote: "공개를 거두면 소장한 회원도 더 볼 수 없게 돼요.",
  restrictedStatus: "운영 정책에 따라 노벨에서 내려졌어요. 소장한 회원도 지금은 볼 수 없어요.",
  salesStoppedStatus: SALES_STOPPED_STATUS,
};

const ON: BuyerPolicyCopy = {
  withdrawConfirm:
    "목록과 작품 화면에서 바로 사라지고 새로 소장할 수 없게 돼요. 이미 소장한 회원은 산 화와 무료 화를 계속 읽을 수 있어요. 나중에 다시 공개하면 다시 판매돼요.",
  withdrawnStatus: "공개를 거둔 소설이에요. 노벨에 보이지 않고 새로 소장할 수 없어요. 이미 소장한 회원은 산 화를 계속 읽어요.",
  withdrawnReopen: "다시 공개하면 다시 판매돼요.",
  publishWithdrawNote: "공개를 거두면 새로 소장할 수 없게 되고, 이미 소장한 회원은 계속 읽어요.",
  restrictedStatus: "운영 정책에 따라 노벨에서 내려졌어요. 소장한 회원도 지금은 볼 수 없고, 쓴 클로버는 돌려드렸어요.",
  salesStoppedStatus: SALES_STOPPED_STATUS,
};

export function toBuyerPolicyCopy(pricing: { novelPublicPolicyV2Enabled?: boolean } | undefined): BuyerPolicyCopy {
  return pricing?.novelPublicPolicyV2Enabled === true ? ON : OFF;
}
