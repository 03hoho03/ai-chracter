import { describe, expect, it } from "vitest";

import { APPLY_CONSENT_NOTICE } from "./consentNotice";

const noticeText = APPLY_CONSENT_NOTICE.map((item) => `${item.term} ${item.detail}`).join("\n");

describe("APPLY_CONSENT_NOTICE", () => {
  // 법이 동의 때 알리라고 정한 네 가지가 하나라도 빠지면 그 동의로 받은 수집의 근거가 흔들린다.
  it.each([
    ["수집·이용 목적", "수집·이용 목적"],
    ["수집 항목", "수집 항목"],
    ["신청 기록은 탈퇴하면 파기", "신청 기록(신청·동의 시각, 처리 결과와 사유, 적립 시작·종료 시각)은 탈퇴할 때까지 보유하고 탈퇴하면 지체 없이 파기"],
    ["확정한 정산금과 내역은 세법에 따라 5년 보존", "확정한 정산금과 그 내역은 세법에 따른 장부로서 5년간 보존하며, 탈퇴해도"],
    ["거부할 권리", "동의를 거부할 수 있어요"],
    ["거부에 따른 불이익", "크리에이터 정산을 신청할 수 없지만"],
  ])("고지에 %s 이 있다", (_name, keyword) => {
    expect(noticeText).toContain(keyword);
  });
});
