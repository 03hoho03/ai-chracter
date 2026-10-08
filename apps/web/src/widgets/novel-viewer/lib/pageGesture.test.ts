import { describe, expect, it } from "vitest";

import { type PageGestureInput, toPageGesture, toSettleDurationMs, toTapZone } from "./pageGesture";

// 400px 창, 한 화면 400px(15% = 60px). 가운데를 짧게 누른 탭에서 시작한다.
const TAP: PageGestureInput = {
  dx: 0,
  dy: 0,
  dt: 100,
  velocityX: 0,
  clientX: 200,
  viewportWidth: 400,
  pageWidth: 400,
  targetIsInteractive: false,
  isSettingsOpen: false,
  isZoomed: false,
};

// 탭이 되지 않을 만큼 오래 누른 채 천천히 끈 손짓.
const DRAG: PageGestureInput = { ...TAP, dt: 1000 };

describe("toTapZone", () => {
  it("왼쪽 25% 는 이전, 오른쪽 25% 는 다음, 경계를 포함한 가운데는 바 토글이다", () => {
    expect(toTapZone(0, 1440)).toBe("previous");
    expect(toTapZone(359, 1440)).toBe("previous");
    expect(toTapZone(360, 1440)).toBe("center");
    expect(toTapZone(1080, 1440)).toBe("center");
    expect(toTapZone(1081, 1440)).toBe("next");
    expect(toTapZone(1439, 1440)).toBe("next");
  });
});

describe("toPageGesture — 탭", () => {
  it("영역대로 넘기거나 바를 여닫는다", () => {
    expect(toPageGesture({ ...TAP, clientX: 50 })).toBe("previous");
    expect(toPageGesture(TAP)).toBe("toggle-chrome");
    expect(toPageGesture({ ...TAP, clientX: 350 })).toBe("next");
  });

  it("탭을 스와이프보다 먼저 본다 — 짧게 빨리 움직여도 10px 안이면 탭이다", () => {
    // 9px 을 20ms 에 움직이면 0.45px/ms 라 속도 기준은 넘지만 탭이다.
    expect(toPageGesture({ ...TAP, dx: -9, dt: 20, velocityX: -0.45 })).toBe("toggle-chrome");
  });

  it("탭 거리·시간 경계는 바 토글 판정과 같다", () => {
    expect(toPageGesture({ ...TAP, dx: -10, dt: 20, velocityX: -0.5 })).toBe("next");
    expect(toPageGesture({ ...TAP, dt: 300 })).toBe("settle");
  });

  it("보기 설정이 열려 있으면 어느 영역의 탭이든 설정만 닫는다", () => {
    expect(toPageGesture({ ...TAP, isSettingsOpen: true })).toBe("close-settings");
    expect(toPageGesture({ ...TAP, clientX: 50, isSettingsOpen: true })).toBe("close-settings");
    expect(toPageGesture({ ...TAP, clientX: 350, isSettingsOpen: true })).toBe("close-settings");
  });

  it("링크·버튼 위의 탭은 그 요소에 맡긴다", () => {
    expect(toPageGesture({ ...TAP, targetIsInteractive: true })).toBe("none");
    expect(toPageGesture({ ...TAP, clientX: 350, targetIsInteractive: true })).toBe("none");
    expect(toPageGesture({ ...TAP, targetIsInteractive: true, isSettingsOpen: true })).toBe("none");
  });

  it("확대 중에는 좌·우 탭이 넘기지 않고 가운데 탭만 바를 여닫는다", () => {
    expect(toPageGesture({ ...TAP, clientX: 50, isZoomed: true })).toBe("none");
    expect(toPageGesture({ ...TAP, clientX: 350, isZoomed: true })).toBe("none");
    expect(toPageGesture({ ...TAP, isZoomed: true })).toBe("toggle-chrome");
  });
});

describe("toPageGesture — 스와이프·끌기", () => {
  it("쪽 폭의 15% 이상 끌면 넘긴다", () => {
    expect(toPageGesture({ ...DRAG, dx: -59 })).toBe("settle");
    expect(toPageGesture({ ...DRAG, dx: -60 })).toBe("next");
    expect(toPageGesture({ ...DRAG, dx: 60 })).toBe("previous");
  });

  it("짧게 끌어도 손을 뗄 때 0.3px/ms 이상이면 넘긴다", () => {
    expect(toPageGesture({ ...DRAG, dx: -20, velocityX: -0.29 })).toBe("settle");
    expect(toPageGesture({ ...DRAG, dx: -20, velocityX: -0.3 })).toBe("next");
    expect(toPageGesture({ ...DRAG, dx: 20, velocityX: 0.3 })).toBe("previous");
  });

  it("끈 방향과 반대로 튕겨 놓으면 속도로는 넘기지 않는다", () => {
    expect(toPageGesture({ ...DRAG, dx: -20, velocityX: 0.5 })).toBe("settle");
  });

  it("세로 이동이 더 크면 넘기지 않고 제자리로 돌아간다", () => {
    expect(toPageGesture({ ...DRAG, dx: -100, dy: 101, velocityX: -1 })).toBe("settle");
    expect(toPageGesture({ ...DRAG, dx: -100, dy: 100 })).toBe("next");
  });

  it("링크 위에서 시작한 스와이프도 넘기고, 설정이 열려 있어도 넘긴다", () => {
    expect(toPageGesture({ ...DRAG, dx: -100, targetIsInteractive: true })).toBe("next");
    expect(toPageGesture({ ...DRAG, dx: -100, isSettingsOpen: true })).toBe("next");
  });

  it("확대 중에는 넘기지 않는다", () => {
    expect(toPageGesture({ ...DRAG, dx: -200, velocityX: -1, isZoomed: true })).toBe("none");
  });
});

describe("toSettleDurationMs", () => {
  it("한 화면 전체면 250ms, 남은 거리에 비례해 줄어든다", () => {
    expect(toSettleDurationMs({ remainingPx: 400, pageWidth: 400 })).toBe(250);
    expect(toSettleDurationMs({ remainingPx: -200, pageWidth: 400 })).toBe(125);
  });

  it("80ms 아래로 줄지 않고 250ms 를 넘지 않는다", () => {
    expect(toSettleDurationMs({ remainingPx: 10, pageWidth: 400 })).toBe(80);
    expect(toSettleDurationMs({ remainingPx: 800, pageWidth: 400 })).toBe(250);
  });
});
