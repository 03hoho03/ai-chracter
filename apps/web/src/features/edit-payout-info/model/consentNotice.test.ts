import { describe, expect, it } from "vitest";

import { PAYOUT_INFO_CONSENT_NOTICE } from "./consentNotice";

const noticeText = PAYOUT_INFO_CONSENT_NOTICE.map((item) => `${item.term} ${item.detail}`).join("\n");

describe("PAYOUT_INFO_CONSENT_NOTICE", () => {
  // 법이 동의 때 알리라고 정한 것이 하나라도 빠지면 그 동의로 받은 수집·국외 이전의 근거가 흔들린다.
  it.each([
    ["수집·이용 목적", "수집·이용 목적"],
    ["주민등록번호를 받는다는 사실", "주민등록번호"],
    ["지급에 쓰인 정보의 5년 보존", "5년간 보존하며, 탈퇴해도"],
    ["쓰인 적 없는 정보의 탈퇴 시 파기", "쓰인 적이 없으면 탈퇴할 때 즉시 파기"],
    ["국외 이전받는 자와 국가", "Cloudflare, Inc.(미국"],
    ["국외 이전의 보유 기간", "일간 7일·주간 4주"],
    ["거부할 권리", "동의를 거부할 수 있어요"],
    ["거부에 따른 불이익", "정산금을 지급받을 수 없지만"],
  ])("고지에 %s 이 있다", (_name, keyword) => {
    expect(noticeText).toContain(keyword);
  });
});
