import { describe, expect, it } from "vitest";

import { isMouseReleasedElsewhere, shouldGuardEdgeTouch, shouldSuppressClick } from "./pointerGuard";

describe("shouldSuppressClick", () => {
  it("끌기로 끝난 뗌 바로 뒤의 포인터 click 을 막는다", () => {
    expect(shouldSuppressClick({ suppressedAt: 1000, clickAt: 1005, detail: 1 })).toBe(true);
    expect(shouldSuppressClick({ suppressedAt: 1000, clickAt: 1100, detail: 1 })).toBe(true);
  });

  it("표시 뒤 시간이 지난 click 은 그 끌기의 것이 아니라 막지 않는다", () => {
    expect(shouldSuppressClick({ suppressedAt: 1000, clickAt: 1101, detail: 1 })).toBe(false);
  });

  it("키보드·보조기기 활성화(detail 0)는 표시가 있어도 막지 않는다", () => {
    expect(shouldSuppressClick({ suppressedAt: 1000, clickAt: 1001, detail: 0 })).toBe(false);
  });

  it("끌기 표시가 없으면 막지 않는다", () => {
    expect(shouldSuppressClick({ suppressedAt: undefined, clickAt: 1001, detail: 1 })).toBe(false);
  });
});

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
