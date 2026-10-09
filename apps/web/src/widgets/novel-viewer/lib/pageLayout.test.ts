import { describe, expect, it } from "vitest";

import {
  clampScreen,
  type PageLayoutInput,
  toColumnCount,
  toNearestScreen,
  toPageGeometry,
  toScreenCount,
  toScrollLeft,
} from "./pageLayout";

const NO_SAFE_AREA = { left: 0, right: 0, top: 0, bottom: 0 };

// 글자 16px·줄 간격 1.625·여백 보통(24px)에 Pretendard 로 잰 65ch.
const BASE: PageLayoutInput = {
  width: 390,
  height: 844,
  safeArea: NO_SAFE_AREA,
  isFinePointer: false,
  pagePaddingPx: 24,
  proseWidthPx: 619.5,
  lineHeightPx: 26,
};

describe("toColumnCount", () => {
  it("폭 1024px 부터 두 쪽을 펼친다", () => {
    expect(toColumnCount({ width: 1023, height: 768 })).toBe(1);
    expect(toColumnCount({ width: 1024, height: 768 })).toBe(2);
  });

  it("세로로 긴 화면은 넓어도 한 쪽이고, 정사각은 가로로 친다", () => {
    expect(toColumnCount({ width: 1024, height: 1366 })).toBe(1);
    expect(toColumnCount({ width: 1024, height: 1025 })).toBe(1);
    expect(toColumnCount({ width: 1024, height: 1024 })).toBe(2);
    expect(toColumnCount({ width: 1440, height: 900 })).toBe(2);
  });
});

describe("toPageGeometry", () => {
  it("터치 폰은 넘김 버튼 자리 없이 창 폭에서 여백만 뺀다", () => {
    expect(toPageGeometry(BASE)).toEqual({
      columnCount: 1,
      columnWidth: 342,
      columnGap: 48,
      step: 390,
      columnHeight: 754, // (844 - 80) / 26 = 29.4 → 29줄
      left: 0,
      top: 40,
    });
  });

  it("정밀 포인터면 좌우에 버튼 자리 56px 씩을 먼저 뺀다", () => {
    const geometry = toPageGeometry({ ...BASE, width: 500, height: 800, isFinePointer: true });

    expect(geometry.columnWidth).toBe(500 - 112 - 48);
    expect(geometry.step).toBe(388);
    expect(geometry.left).toBe(56);
  });

  it("쪽 상자(여백 포함)는 65ch 에서 멈추고 남는 폭에서 가운데에 놓인다", () => {
    const geometry = toPageGeometry({ ...BASE, width: 900, height: 800, isFinePointer: true });

    expect(geometry.columnWidth).toBe(619 - 48);
    expect(geometry.step).toBe(619);
    expect(geometry.left).toBe(56 + Math.floor((900 - 112 - 619) / 2));
  });

  it("펼침이면 두 쪽과 그 사이 간격(= 여백 둘)이 한 화면이다", () => {
    const geometry = toPageGeometry({ ...BASE, width: 1024, height: 768, isFinePointer: true });

    expect(geometry.columnCount).toBe(2);
    expect(geometry.columnWidth).toBe(Math.floor((1024 - 112) / 2) - 48);
    expect(geometry.step).toBe(2 * (408 + 48));
    expect(geometry.left).toBe(56);
  });

  it("단 간격은 여백 설정을 따른다", () => {
    expect(toPageGeometry({ ...BASE, pagePaddingPx: 16 }).columnGap).toBe(32);
    expect(toPageGeometry({ ...BASE, pagePaddingPx: 32 }).columnGap).toBe(64);
  });

  it("창 폭이 소수여도 단 폭·화면 폭·위치는 정수다", () => {
    const geometry = toPageGeometry({
      ...BASE,
      width: 1366.4,
      height: 768,
      safeArea: { left: 0.3, right: 0, top: 0, bottom: 0 },
      isFinePointer: true,
      proseWidthPx: 2000,
    });

    expect(Number.isInteger(geometry.columnWidth)).toBe(true);
    expect(Number.isInteger(geometry.step)).toBe(true);
    expect(geometry.step).toBe(2 * (geometry.columnWidth + geometry.columnGap));
    expect(geometry.left).toBe(56); // 0.3 + 56 + 0.05 를 내림
  });

  it("잰 여백이 소수여도 단 간격·단 폭·화면 폭은 정수다", () => {
    const geometry = toPageGeometry({ ...BASE, pagePaddingPx: 23.25 }); // 1.5rem 을 15.5px 루트에서 잰 값

    expect(geometry.columnGap).toBe(46);
    expect(geometry.columnWidth).toBe(390 - 46);
    expect(geometry.step).toBe(390);
  });

  it("레이아웃 전 입력(0)에서도 NaN 이 없고 단 폭은 음수가 아니다", () => {
    const geometry = toPageGeometry({
      width: 0,
      height: 0,
      safeArea: NO_SAFE_AREA,
      isFinePointer: false,
      pagePaddingPx: 24,
      proseWidthPx: 0,
      lineHeightPx: 0,
    });

    for (const value of Object.values(geometry)) expect(Number.isNaN(value)).toBe(false);
    expect(geometry.columnWidth).toBe(0);
    expect(geometry.columnHeight).toBe(0);
  });

  it("창 높이는 쟀지만 줄 높이를 아직 모르면 단 높이는 NaN 이 아니라 0 이다", () => {
    expect(toPageGeometry({ ...BASE, lineHeightPx: 0 }).columnHeight).toBe(0);
  });

  it("가로 safe-area 는 쓸 폭에서 빠지고 위·아래 safe-area 는 여백에 더해진다", () => {
    const geometry = toPageGeometry({ ...BASE, safeArea: { left: 20, right: 10, top: 47, bottom: 34 } });

    expect(geometry.columnWidth).toBe(390 - 30 - 48);
    expect(geometry.left).toBe(20);
    expect(geometry.top).toBe(87);
    expect(geometry.columnHeight).toBe(Math.floor((844 - 87 - 74) / 26) * 26);
  });

  it("단 높이는 소수 줄 높이에서도 줄 높이의 정수배다", () => {
    const geometry = toPageGeometry({ ...BASE, lineHeightPx: 29.25 });

    expect(geometry.columnHeight).toBe(26 * 29.25); // (844 - 80) / 29.25 = 26.1 → 26줄로 내림
  });

  it("줄 하나도 안 들어가는 낮은 창에서도 한 줄은 남긴다", () => {
    expect(toPageGeometry({ ...BASE, height: 90 }).columnHeight).toBe(26);
  });
});

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
