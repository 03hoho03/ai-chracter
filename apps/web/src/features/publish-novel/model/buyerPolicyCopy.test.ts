import { describe, expect, it } from "vitest";

import { toBuyerPolicyCopy } from "./buyerPolicyCopy";

describe("toBuyerPolicyCopy", () => {
  it.each([undefined, {}, { novelPublicPolicyV2Enabled: false }])(
    "스위치가 꺼졌거나 값이 없으면 지금 문장 그대로다 (%#)",
    (pricing) => {
      expect(toBuyerPolicyCopy(pricing)).toEqual({
        withdrawConfirm:
          "목록과 작품 화면에서 바로 사라지고, 소장한 회원도 더 볼 수 없게 돼요. 클로버는 돌려드리지 않아요. 나중에 다시 공개하면 소장한 화도 다시 열려요.",
        withdrawnStatus: "공개를 거둔 소설이에요. 노벨에 보이지 않고, 소장한 회원도 지금은 볼 수 없어요.",
        withdrawnReopen: "다시 공개하면 소장한 화도 다시 열려요.",
        publishWithdrawNote: "공개를 거두면 소장한 회원도 더 볼 수 없게 돼요.",
        restrictedStatus: "운영 정책에 따라 노벨에서 내려졌어요. 소장한 회원도 지금은 볼 수 없어요.",
        salesStoppedStatus:
          "운영 정책에 따라 판매가 멈췄어요. 노벨 목록에 보이지 않고 새로 소장할 수 없어요. 소장한 회원도 지금은 볼 수 없어요.",
      });
    },
  );

  it("스위치가 켜지면 거둬도 소장한 회원은 계속 읽는다고 말하고 못 본다고 하지 않는다", () => {
    const copy = toBuyerPolicyCopy({ novelPublicPolicyV2Enabled: true });
    for (const line of [copy.withdrawConfirm, copy.withdrawnStatus, copy.publishWithdrawNote]) {
      expect(line).toContain("계속 읽");
      expect(line).not.toContain("볼 수 없");
    }
    expect(copy.withdrawnReopen).not.toContain("다시 열려요");
  });

  it("판매 중단은 켜짐에서도 소장한 회원이 계속 읽는다고 말한다", () => {
    expect(toBuyerPolicyCopy({ novelPublicPolicyV2Enabled: true }).salesStoppedStatus).toBe(
      "운영 정책에 따라 판매가 멈췄어요. 노벨 목록에 보이지 않고 새로 소장할 수 없어요. 이미 소장한 회원은 계속 읽어요.",
    );
  });

  it("스위치가 켜지면 운영 이용제한은 클로버를 돌려드렸다고 말한다", () => {
    expect(toBuyerPolicyCopy({ novelPublicPolicyV2Enabled: true }).restrictedStatus).toContain("돌려드렸어요");
  });
});
