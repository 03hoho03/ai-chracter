import { describe, expect, it } from "vitest";

import {
  clampScreen,
  toNearestScreen,
  toPageCount,
  toPageLabel,
  toScreenCount,
  toScrollLeft,
  toVisiblePages,
} from "./pageLayout";

describe("toScreenCount", () => {
  it("한 쪽이면 단 하나가 한 화면이다", () => {
    expect(toScreenCount({ lastColumnIndex: 0, columnCount: 1 })).toBe(1);
    expect(toScreenCount({ lastColumnIndex: 8, columnCount: 1 })).toBe(9);
  });

  it("펼침이면 두 단이 한 화면이다", () => {
    expect(toScreenCount({ lastColumnIndex: 0, columnCount: 2 })).toBe(1);
    expect(toScreenCount({ lastColumnIndex: 1, columnCount: 2 })).toBe(1);
    expect(toScreenCount({ lastColumnIndex: 2, columnCount: 2 })).toBe(2);
    expect(toScreenCount({ lastColumnIndex: 10, columnCount: 2 })).toBe(6);
  });
});

describe("clampScreen", () => {
  it("첫 화면 앞과 화 끝 화면 뒤로 가지 않는다", () => {
    expect(clampScreen(-1, 5)).toBe(0);
    expect(clampScreen(0, 5)).toBe(0);
    expect(clampScreen(4, 5)).toBe(4);
    expect(clampScreen(5, 5)).toBe(4);
  });

  it("화면 수가 0 이어도 0 이다", () => {
    expect(clampScreen(0, 0)).toBe(0);
    expect(clampScreen(3, 0)).toBe(0);
  });
});

describe("toScrollLeft", () => {
  it("화면 번호 × 화면 폭이다", () => {
    expect(toScrollLeft(0, 390)).toBe(0);
    expect(toScrollLeft(3, 912)).toBe(2736);
  });
});

describe("toNearestScreen", () => {
  it("화면 사이에 걸친 위치를 가까운 화면으로 맞춘다", () => {
    expect(toNearestScreen({ scrollLeft: 194, step: 390, screenCount: 5 })).toBe(0);
    expect(toNearestScreen({ scrollLeft: 195, step: 390, screenCount: 5 })).toBe(1);
    expect(toNearestScreen({ scrollLeft: 780, step: 390, screenCount: 5 })).toBe(2);
  });

  it("레이아웃 전(폭 0·화면 0)에는 첫 화면이다", () => {
    expect(toNearestScreen({ scrollLeft: 0, step: 0, screenCount: 0 })).toBe(0);
    expect(toNearestScreen({ scrollLeft: 120, step: 0, screenCount: 5 })).toBe(0);
  });

  it("범위를 벗어난 위치는 첫·끝 화면으로 자른다", () => {
    expect(toNearestScreen({ scrollLeft: -50, step: 390, screenCount: 5 })).toBe(0);
    expect(toNearestScreen({ scrollLeft: 9999, step: 390, screenCount: 5 })).toBe(4);
  });
});

describe("논리 쪽", () => {
  // 한 장: 화 끝까지 18단. 펼침: 본문 0~14단, 15단이 화 끝을 새 펼침 왼쪽으로 민 빈 단, 화 끝 16단.
  const SINGLE = { lastColumnIndex: 17, spacerColumnIndex: undefined };
  const SPREAD_WITH_SPACER = { lastColumnIndex: 16, spacerColumnIndex: 15 };
  const SPREAD_WITHOUT_SPACER = { lastColumnIndex: 16, spacerColumnIndex: undefined };

  it("쪽 수는 단 수이고, 펼침의 빈 단은 세지 않는다", () => {
    expect(toPageCount(SINGLE)).toBe(18);
    expect(toPageCount(SPREAD_WITH_SPACER)).toBe(16);
    expect(toPageCount(SPREAD_WITHOUT_SPACER)).toBe(17);
  });

  it("한 장은 화면마다 한 쪽이다", () => {
    expect(toPageLabel({ ...SINGLE, screen: 2, columnCount: 1 })).toBe("3 / 18쪽");
    expect(toPageLabel({ ...SINGLE, screen: 17, columnCount: 1 })).toBe("18 / 18쪽");
  });

  it("펼침은 두 쪽을 en dash 로 잇는다", () => {
    expect(toVisiblePages({ ...SPREAD_WITH_SPACER, screen: 1, columnCount: 2 })).toEqual([3, 4]);
    expect(toPageLabel({ ...SPREAD_WITH_SPACER, screen: 1, columnCount: 2 })).toBe("3–4 / 16쪽");
  });

  it("본문 마지막 쪽 옆이 빈 단이면 그 쪽 하나만, 화 끝 펼침은 화 끝 쪽 하나만 보인다", () => {
    expect(toPageLabel({ ...SPREAD_WITH_SPACER, screen: 7, columnCount: 2 })).toBe("15 / 16쪽");
    expect(toPageLabel({ ...SPREAD_WITH_SPACER, screen: 8, columnCount: 2 })).toBe("16 / 16쪽");
    expect(toPageLabel({ ...SPREAD_WITHOUT_SPACER, screen: 8, columnCount: 2 })).toBe("17 / 17쪽");
  });

  it("빈 단을 켠 펼침도 화 끝 쪽 번호가 한 장으로 볼 때와 같다", () => {
    // 같은 화를 한 장으로 재면 화 끝이 16번째 단(15)에 온다.
    const single = { lastColumnIndex: 15, spacerColumnIndex: undefined };
    const lastSingle = toVisiblePages({ ...single, screen: 15, columnCount: 1 });
    const lastSpread = toVisiblePages({ ...SPREAD_WITH_SPACER, screen: 8, columnCount: 2 });

    expect(lastSpread).toEqual(lastSingle);
  });
});
