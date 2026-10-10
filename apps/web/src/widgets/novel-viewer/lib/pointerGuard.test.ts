import { describe, expect, it } from "vitest";

import { isMouseReleasedElsewhere, shouldGuardEdgeTouch } from "./pointerGuard";

describe("shouldGuardEdgeTouch", () => {
  const base = { viewportWidth: 390, touchCount: 1, isOnInteractive: false };

  it("가장자리 20px 안에서 시작한 한 손가락 터치를 막는다", () => {
    expect(shouldGuardEdgeTouch({ ...base, clientX: 19 })).toBe(true);
    expect(shouldGuardEdgeTouch({ ...base, clientX: 20 })).toBe(false);
    expect(shouldGuardEdgeTouch({ ...base, clientX: 370 })).toBe(false);
    expect(shouldGuardEdgeTouch({ ...base, clientX: 371 })).toBe(true);
  });

  it("링크·버튼 위의 터치는 가장자리여도 막지 않는다", () => {
    expect(shouldGuardEdgeTouch({ ...base, clientX: 18, isOnInteractive: true })).toBe(false);
  });

  it("두 손가락(핀치)은 막지 않는다", () => {
    expect(shouldGuardEdgeTouch({ ...base, clientX: 5, touchCount: 2 })).toBe(false);
  });
});

describe("isMouseReleasedElsewhere", () => {
  it("왼쪽 버튼이 놓인 마우스 움직임이면 참이다", () => {
    expect(isMouseReleasedElsewhere({ pointerType: "mouse", buttons: 0 })).toBe(true);
    expect(isMouseReleasedElsewhere({ pointerType: "mouse", buttons: 2 })).toBe(true);
  });

  it("왼쪽 버튼을 누른 채면 거짓이다", () => {
    expect(isMouseReleasedElsewhere({ pointerType: "mouse", buttons: 1 })).toBe(false);
    expect(isMouseReleasedElsewhere({ pointerType: "mouse", buttons: 3 })).toBe(false);
  });

  it("터치·펜은 보지 않는다", () => {
    expect(isMouseReleasedElsewhere({ pointerType: "touch", buttons: 0 })).toBe(false);
    expect(isMouseReleasedElsewhere({ pointerType: "pen", buttons: 0 })).toBe(false);
  });
});
