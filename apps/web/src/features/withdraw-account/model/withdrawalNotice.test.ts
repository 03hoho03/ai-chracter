import { describe, expect, it } from "vitest";

import { toWithdrawalNotice } from "./withdrawalNotice";

// 스위치가 꺼져 있을 때의 문장은 이 분기를 넣기 전의 문장과 한 글자도 다르지 않아야 한다.
const TODAY =
  "탈퇴하면 발행한 캐릭터·스토리는 비공개로 전환되고, 대화기록과 만든 소설은 삭제돼요. 작성 중인 초안은 보존되지만 탈퇴 후에는 접근할 수 없어요. 이 작업은 되돌릴 수 없어요.";

describe("toWithdrawalNotice", () => {
  it.each([undefined, {}, { novelPublicPolicyV2Enabled: false }])("스위치가 꺼졌거나 모르면 지금 문장이다 (%o)", (pricing) => {
    expect(toWithdrawalNotice(pricing)).toBe(TODAY);
  });

  it("켜져 있으면 노벨에서 팔린 소설은 남아 산 회원이 계속 읽고 환급이 없다고 말한다", () => {
    expect(toWithdrawalNotice({ novelPublicPolicyV2Enabled: true })).toBe(
      "탈퇴하면 발행한 캐릭터·스토리는 비공개로 전환되고, 대화기록과 만든 소설은 삭제돼요. 다만 노벨에서 팔린 소설은 작가 정보 없이 남아 산 회원이 계속 읽어요(산 회원에게 클로버를 돌려드리지 않아요). 작성 중인 초안은 보존되지만 탈퇴 후에는 접근할 수 없어요. 이 작업은 되돌릴 수 없어요.",
    );
  });
});
