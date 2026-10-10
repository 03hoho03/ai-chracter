// `packages/ui` 에는 테스트 러너가 없어 그 패키지의 순수 함수를 여기서 검사한다. web CI 는 `packages/**` 만 바뀐
// 변경에서도 돈다.
import {
  shouldSuppressClickAfterSwipe,
  toReleaseVelocity,
  toSheetSettleDurationMs,
  toSheetSwipeOffset,
  toSheetSwipeRelease,
  toSheetSwipeStart,
} from "@ai-character-chat/ui/lib/sheet-swipe";
import { describe, expect, it } from "vitest";

describe("toSheetSwipeStart", () => {
  it("10px 에 못 미친 움직임은 아직 정하지 않는다", () => {
    expect(toSheetSwipeStart({ dx: -9, dy: 0 })).toBe("pending");
    expect(toSheetSwipeStart({ dx: -6, dy: -7 })).toBe("pending");
  });

  it("10px 를 움직인 순간 가로가 세로보다 크고 왼쪽이면 끌기다", () => {
    expect(toSheetSwipeStart({ dx: -10, dy: 0 })).toBe("drag");
    expect(toSheetSwipeStart({ dx: -12, dy: 8 })).toBe("drag");
  });

  it("세로가 먼저이거나 가로와 같으면 끌기가 아니다", () => {
    expect(toSheetSwipeStart({ dx: -3, dy: 12 })).toBe("ignore");
    expect(toSheetSwipeStart({ dx: -8, dy: -8 })).toBe("ignore");
  });

  it("오른쪽으로 움직이면 끌기가 아니다", () => {
    expect(toSheetSwipeStart({ dx: 12, dy: 0 })).toBe("ignore");
  });
});

describe("toSheetSwipeOffset", () => {
  it("왼쪽 이동은 그대로 따라온다", () => {
    expect(toSheetSwipeOffset(-40)).toBe(-40);
  });

  it("오른쪽으로는 제자리에서 멈춘다", () => {
    expect(toSheetSwipeOffset(30)).toBe(0);
  });
});

describe("toSheetSwipeRelease", () => {
  const sheetWidth = 300;

  it("시트 폭의 1/3 이상 끌었으면 닫는다", () => {
    expect(toSheetSwipeRelease({ dx: -100, velocityX: 0, sheetWidth })).toBe("close");
  });

  it("1/3 에 못 미치고 천천히 놓으면 제자리로 돌아간다", () => {
    expect(toSheetSwipeRelease({ dx: -99, velocityX: -0.29, sheetWidth })).toBe("settle");
  });

  it("짧게 끌었어도 왼쪽으로 0.3px/ms 이상 튕기면 닫는다", () => {
    expect(toSheetSwipeRelease({ dx: -20, velocityX: -0.3, sheetWidth })).toBe("close");
  });

  it("많이 끌었어도 오른쪽으로 튕기며 놓으면 돌아간다", () => {
    expect(toSheetSwipeRelease({ dx: -200, velocityX: 0.3, sheetWidth })).toBe("settle");
  });

  it("오른쪽으로 끌고 놓으면 닫지 않는다", () => {
    expect(toSheetSwipeRelease({ dx: 150, velocityX: 0, sheetWidth })).toBe("settle");
  });

  it("시트 폭을 모르면 거리로는 닫지 않는다", () => {
    expect(toSheetSwipeRelease({ dx: -100, velocityX: 0, sheetWidth: 0 })).toBe("settle");
  });
});

describe("toSheetSettleDurationMs", () => {
  it("남은 거리에 비례하고 80~250ms 안에 든다", () => {
    expect(toSheetSettleDurationMs({ remainingPx: 300, sheetWidth: 300 })).toBe(250);
    expect(toSheetSettleDurationMs({ remainingPx: -150, sheetWidth: 300 })).toBe(125);
    expect(toSheetSettleDurationMs({ remainingPx: 6, sheetWidth: 300 })).toBe(80);
  });

  it("시트 폭을 모르면 0 이다", () => {
    expect(toSheetSettleDurationMs({ remainingPx: 50, sheetWidth: 0 })).toBe(0);
  });
});

describe("toReleaseVelocity", () => {
  it("놓기 전 100ms 안의 움직임으로 잰다", () => {
    const samples = [
      { x: 0, time: 0 },
      { x: -10, time: 100 },
      { x: -20, time: 150 },
    ];
    // 0ms 표본은 250ms 에서 100ms 밖이라 빠지고, 150ms 에서 250ms 까지 -40px 이다.
    expect(toReleaseVelocity(samples, { x: -60, time: 250 })).toBeCloseTo(-0.4);
  });

  it("창 안에 앞선 표본이 없으면 0 이다", () => {
    expect(toReleaseVelocity([{ x: 0, time: 0 }], { x: -50, time: 300 })).toBe(0);
  });
});

describe("shouldSuppressClickAfterSwipe", () => {
  it("끌기로 끝난 뗌 바로 뒤의 포인터 click 은 막는다", () => {
    expect(shouldSuppressClickAfterSwipe({ suppressedAt: 1000, clickAt: 1010, detail: 1 })).toBe(true);
    expect(shouldSuppressClickAfterSwipe({ suppressedAt: 1000, clickAt: 1100, detail: 1 })).toBe(true);
  });

  it("끌기 표시가 없거나 시간이 지났으면 막지 않는다", () => {
    expect(shouldSuppressClickAfterSwipe({ suppressedAt: undefined, clickAt: 1010, detail: 1 })).toBe(false);
    expect(shouldSuppressClickAfterSwipe({ suppressedAt: 1000, clickAt: 1101, detail: 1 })).toBe(false);
  });

  it("키보드·보조기기 활성화(detail 0)는 막지 않는다", () => {
    expect(shouldSuppressClickAfterSwipe({ suppressedAt: 1000, clickAt: 1010, detail: 0 })).toBe(false);
  });
});
