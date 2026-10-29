import { describe, expect, it } from "vitest";

import { claimReplacesButton } from "./claimFocus";

describe("claimReplacesButton", () => {
  // 지급 여부로 보면 이 갈래를 놓친다 — 이미 받은 날 누르면 지급 없이도 받은 판이 와서 버튼이 사라진다.
  it("지급되지 않았어도 오늘 받은 판이 오면 버튼이 사라진다", () => {
    expect(claimReplacesButton({ board: { canClaimToday: false } })).toBe(true);
  });

  it("아직 받을 수 있는 판이 오면 버튼이 남는다", () => {
    expect(claimReplacesButton({ board: { canClaimToday: true } })).toBe(false);
  });

  it("확인 중·인증 안내는 버튼을 대신하고, 실패·잠시 멈춤·꺼짐은 그 자리에서 버튼을 바꾸지 않는다", () => {
    expect(claimReplacesButton({ error: "checking" })).toBe(true);
    expect(claimReplacesButton({ error: "identity" })).toBe(true);
    expect(claimReplacesButton({ error: "failed" })).toBe(false);
    expect(claimReplacesButton({ error: "paused" })).toBe(false);
    expect(claimReplacesButton({ error: "off" })).toBe(false);
  });
});
