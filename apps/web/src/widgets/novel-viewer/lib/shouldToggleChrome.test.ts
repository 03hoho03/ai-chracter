import { describe, expect, it } from "vitest";

import { type ChromeTapGesture, shouldToggleChrome } from "./shouldToggleChrome";

const TAP: ChromeTapGesture = { dx: 0, dy: 0, dt: 100, selectionCollapsed: true, targetIsInteractive: false };

describe("shouldToggleChrome", () => {
  it("제자리에서 짧게 누른 탭은 바를 여닫는다", () => {
    expect(shouldToggleChrome(TAP)).toBe(true);
  });

  it("이동 거리는 두 축을 합친 직선 거리로 잰다", () => {
    expect(shouldToggleChrome({ ...TAP, dx: 6, dy: 7 })).toBe(true); // 약 9.2px
    expect(shouldToggleChrome({ ...TAP, dx: 6, dy: 8 })).toBe(false); // 10px
    expect(shouldToggleChrome({ ...TAP, dx: -9.9 })).toBe(true);
    expect(shouldToggleChrome({ ...TAP, dy: -10 })).toBe(false);
  });

  it("300ms 이상 누르면 탭이 아니다", () => {
    expect(shouldToggleChrome({ ...TAP, dt: 299 })).toBe(true);
    expect(shouldToggleChrome({ ...TAP, dt: 300 })).toBe(false);
  });

  it("문장을 선택했으면 탭이 아니다", () => {
    expect(shouldToggleChrome({ ...TAP, selectionCollapsed: false })).toBe(false);
  });

  it("링크·버튼 위에서 누르면 탭이 아니다", () => {
    expect(shouldToggleChrome({ ...TAP, targetIsInteractive: true })).toBe(false);
  });
});
