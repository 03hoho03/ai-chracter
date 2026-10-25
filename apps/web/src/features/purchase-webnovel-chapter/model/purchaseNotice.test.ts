import { describe, expect, it } from "vitest";

import { toPurchaseNotice } from "./purchaseNotice";

describe("toPurchaseNotice", () => {
  // 스위치가 꺼져 있을 때의 문장은 이 분기를 넣기 전에 모달이 그리던 문장과 한 글자도 다르지 않아야 한다.
  it.each([undefined, {}, { novelPublicPolicyV2Enabled: false }])("스위치가 꺼졌거나 값이 없으면 지금 문장 그대로다 (%#)", (pricing) => {
    expect(toPurchaseNotice(pricing)).toEqual({
      lead: "구매한 화는 공개가 유지되는 동안 볼 수 있어요.",
      detail:
        "소장하면 바로 열려 구매를 취소할 수 없고, 게시자의 공개 철회·탈퇴나 원작 제한·운영 조치로 공개가 끝나도 열람에 쓴 클로버는 돌려드리지 않아요(운영자의 잘못으로 끝난 경우는 제외). 게시자가 소설을 삭제하면 클로버가 자동으로 돌아와요.",
    });
  });

  it("스위치가 켜지면 판 고르기와 계속 읽기, 운영 조치의 자동 환급을 말한다", () => {
    expect(toPurchaseNotice({ novelPublicPolicyV2Enabled: true })).toEqual({
      lead: "소장한 화는 게시자가 고쳐 다시 공개해도 다시 살 필요가 없고, 산 때의 판과 최신 판 가운데 골라 읽을 수 있어요.",
      detail:
        "소장하면 바로 열려 구매를 취소할 수 없어요. 게시자가 공개를 거두거나 소설을 지우거나 탈퇴해도, 판매가 멈춰도 산 화는 계속 읽을 수 있고 이때 클로버는 돌려드리지 않아요. 운영자가 이 소설이나 원작을 이용제한·삭제하면 더 읽을 수 없게 되고, 쓴 클로버는 꺼낸 그대로(유효기간 포함) 자동으로 돌려드려요. 돌려받은 화는 다시 열려도 새로 소장해야 읽을 수 있어요.",
    });
  });
});
