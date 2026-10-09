import { describe, expect, it } from "vitest";

import { APPLY_CONSENT_NOTICE } from "./consentNotice";

const noticeText = APPLY_CONSENT_NOTICE.map((item) => `${item.term} ${item.detail}`).join("\n");

describe("APPLY_CONSENT_NOTICE", () => {
  // 법이 동의 때 알리라고 정한 네 가지가 하나라도 빠지면 그 동의로 받은 수집의 근거가 흔들린다.
  it.each([
    ["수집·이용 목적", "수집·이용 목적"],
    ["수집 항목", "수집 항목"],
    ["보유 기간(마지막 확정·지급 뒤 5년)", "마지막 확정 또는 지급이 있은 날부터 5년"],
    ["거부할 권리", "동의를 거부할 수 있어요"],
    ["거부에 따른 불이익", "크리에이터 정산을 신청할 수 없지만"],
  ])("고지에 %s 이 있다", (_name, keyword) => {
    expect(noticeText).toContain(keyword);
  });
});
