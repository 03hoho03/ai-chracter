import { describe, expect, it } from "vitest";

import {
  isScrollRestored,
  MIN_VISIBLE_PX,
  toCurrentParagraphIndex,
  toReadingBandRootMargin,
  toRestoreScrollTop,
  toTrackingStart,
} from "./readingBand";

describe("toCurrentParagraphIndex", () => {
  it("띠에 걸친 문단 중 가장 앞 문단", () => {
    expect(
      toCurrentParagraphIndex([
        { index: 21, visibleHeight: 120, height: 120 },
        { index: 20, visibleHeight: 60, height: 90 },
      ]),
    ).toBe(20);
  });

  it("앞 문단 아랫변이 1px 도 안 되게 걸친 조각은 세지 않는다(열 때마다 한 문단씩 밀리던 경우)", () => {
    expect(
      toCurrentParagraphIndex([
        { index: 19, visibleHeight: 0.34, height: 84 },
        { index: 20, visibleHeight: 200, height: 200 },
      ]),
    ).toBe(20);
  });

  it("겹침이 최소 높이에 막 닿으면 센다, 바로 아래면 안 센다", () => {
    expect(toCurrentParagraphIndex([{ index: 3, visibleHeight: MIN_VISIBLE_PX, height: 100 }])).toBe(3);
    expect(toCurrentParagraphIndex([{ index: 3, visibleHeight: MIN_VISIBLE_PX - 0.01, height: 100 }])).toBeUndefined();
  });

  it("최소 높이보다 짧은 문단은 통째로 들어와야 센다", () => {
    expect(toCurrentParagraphIndex([{ index: 4, visibleHeight: 6, height: 6 }])).toBe(4);
    expect(toCurrentParagraphIndex([{ index: 4, visibleHeight: 5, height: 6 }])).toBeUndefined();
  });

  it("셀 문단이 없으면 undefined", () => {
    expect(toCurrentParagraphIndex([])).toBeUndefined();
  });
});

describe("toReadingBandRootMargin", () => {
  it("위쪽은 scroll-margin-top + 1px 만큼 잘라 낸다", () => {
    expect(toReadingBandRootMargin(16)).toBe("-17px 0px -60% 0px");
    // 안전 영역이 더해져 소수가 나오면 올림한다.
    expect(toReadingBandRootMargin(63.5)).toBe("-65px 0px -60% 0px");
  });

  it("여백이 없으면 1px 만", () => {
    expect(toReadingBandRootMargin(0)).toBe("-1px 0px -60% 0px");
  });
});

describe("toRestoreScrollTop", () => {
  it("문단 윗변이 scroll-margin 만큼 아래에 오게 한다", () => {
    expect(toRestoreScrollTop({ scrollY: 0, elementTop: 1500, scrollMarginTop: 16 })).toBe(1484);
    expect(toRestoreScrollTop({ scrollY: 300, elementTop: 200, scrollMarginTop: 16 })).toBe(484);
  });

  it("문서 위로는 넘어가지 않는다", () => {
    expect(toRestoreScrollTop({ scrollY: 0, elementTop: 4, scrollMarginTop: 16 })).toBe(0);
  });
});

describe("isScrollRestored", () => {
  it("창이 목표 자리(1px 안)에 있으면 반영됐다", () => {
    expect(isScrollRestored({ scrollY: 2228, targetTop: 2228, maxScrollY: 5000 })).toBe(true);
    expect(isScrollRestored({ scrollY: 2227.4, targetTop: 2228, maxScrollY: 5000 })).toBe(true);
  });

  it("라우터가 맨 위로 올려 0 이면 반영되지 않았다", () => {
    expect(isScrollRestored({ scrollY: 0, targetTop: 2228, maxScrollY: 5000 })).toBe(false);
  });

  it("1px 를 넘게 어긋나면 반영되지 않았다", () => {
    expect(isScrollRestored({ scrollY: 2226, targetTop: 2228, maxScrollY: 5000 })).toBe(false);
  });

  it("문서가 목표보다 짧으면 갈 수 있는 끝에 닿은 것으로 반영됐다", () => {
    expect(isScrollRestored({ scrollY: 1200, targetTop: 1500, maxScrollY: 1200 })).toBe(true);
    expect(isScrollRestored({ scrollY: 0, targetTop: 1500, maxScrollY: 1200 })).toBe(false);
  });
});

describe("toTrackingStart", () => {
  it("되돌린 자리가 반영됐으면(맨 위가 그 자리인 경우 포함) 바로 잰다", () => {
    expect(toTrackingStart("restored")).toBe("now");
  });

  it("되돌리기를 반영하지 못했으면 이용자가 스크롤한 뒤부터(맨 위에서 재면 저장된 자리를 덮는다)", () => {
    expect(toTrackingStart("failed")).toBe("afterUserScroll");
  });

  it("저장된 자리가 없는 화는 덮을 자리가 없어 바로 잰다", () => {
    expect(toTrackingStart("none")).toBe("now");
  });

  it("그 화의 자리를 응답에서 알 수 없으면(옛 API) 이용자가 스크롤한 뒤부터", () => {
    expect(toTrackingStart("unknown")).toBe("afterUserScroll");
  });
});
