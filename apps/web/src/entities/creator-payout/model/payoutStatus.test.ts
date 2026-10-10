import { describe, expect, it } from "vitest";

import { formatPayoutStatus, formatTransferredOn } from "./payoutStatus";

describe("formatPayoutStatus", () => {
  it.each([
    ["requested", "처리 중"],
    ["paid", "이체 완료"],
    ["returned", "반려"],
  ])("%s 는 %s 다", (status, label) => {
    expect(formatPayoutStatus(status)).toBe(label);
  });

  // 서버가 먼저 배포돼 새 상태가 오면 빈 라벨 대신 아직 끝나지 않은 지급으로 읽는다.
  it("모르는 상태는 처리 중으로 읽는다", () => {
    expect(formatPayoutStatus("something_new")).toBe("처리 중");
  });
});

describe("formatTransferredOn", () => {
  it("한국 날짜를 시간대 변환 없이 점 표기로 바꾼다", () => {
    expect(formatTransferredOn("2026-10-01")).toBe("2026.10.01");
  });
});
