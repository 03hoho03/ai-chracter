import { describe, expect, it } from "vitest";

import { PAGE_SCALE_MAX, PAGE_SCALE_MIN, PAGE_SCALE_RESUME, toPageFit, type PageFitInput } from "./pageFit";

const NO_SAFE_AREA = { top: 0, right: 0, bottom: 0, left: 0 };

function fitOf(viewportWidth: number, viewportHeight: number, overrides: Partial<PageFitInput> = {}) {
  return toPageFit({ viewportWidth, viewportHeight, safeArea: NO_SAFE_AREA, isFinePointer: false, wasBelowMinimum: false, ...overrides });
}

// 위·아래 바 자리는 한쪽 57px(줄 56 + 경계선 1)이라 판형이 쓸 수 있는 높이는 창 높이 − 114 다.
describe("toPageFit", () => {
  it("세로 폰은 폭이 배율을 정하고, 판형을 두 바 자리 사이 세로 가운데에 놓는다", () => {
    const fit = fitOf(390, 844);

    expect(fit.columnCount).toBe(1);
    expect(fit.scale).toBeCloseTo(390 / 360, 10);
    expect(fit.isBelowMinimum).toBe(false);
    expect(fit).toMatchObject({ left: 0, width: 390, height: 585, top: Math.floor(57 + (730 - 585) / 2) });
  });

  it("바 자리를 뺀 높이가 배율을 정하는 낮은 폰은 그 높이에 맞춘다", () => {
    // iPhone SE 의 Safari(브라우저 막대가 보이는 창). 바 자리를 빼지 않으면 553 / 540 이 된다.
    const fit = fitOf(375, 553);

    expect(fit.scale).toBeCloseTo((553 - 114) / 540, 10);
    expect(fit.isBelowMinimum).toBe(false);
  });

  it("safe-area 는 바 자리 바깥에 더해 가용 높이에서 빼고, 판형도 그만큼 내려 놓는다", () => {
    const fit = fitOf(375, 667, { safeArea: { top: 20, right: 0, bottom: 0, left: 0 } });

    expect(fit.scale).toBeCloseTo((667 - 114 - 20) / 540, 10);
    expect(fit.top).toBe(Math.floor(57 + 20 + (533 - fit.height) / 2));
  });

  it("배율이 상한을 넘는 화면에서는 상한에서 멈추고 판형 둘레를 비운다", () => {
    const fit = fitOf(768, 1024);

    expect(fit.scale).toBe(PAGE_SCALE_MAX);
    expect(fit.columnCount).toBe(1);
  });

  it("펼쳐도 배율이 줄지 않으면 두 장을 펼친다 — 둘 다 상한에 걸려 같은 값이어도 펼친다", () => {
    const fit = fitOf(1440, 900, { isFinePointer: true });

    expect(fit.columnCount).toBe(2);
    expect(fit.scale).toBe(PAGE_SCALE_MAX);
    expect(fit.width).toBeCloseTo(2 * 360 * 1.2, 10);
  });

  it("펼치면 배율이 줄어드는 화면은 한 장으로 둔다", () => {
    // 펼치면 788 / 720 = 1.094 라 한 장(1.2)보다 글자가 작아진다.
    expect(fitOf(900, 800, { isFinePointer: true }).columnCount).toBe(1);
    // 세로 태블릿도 펼치면 768 / 720 = 1.067 이다.
    expect(fitOf(768, 1024).columnCount).toBe(1);
  });

  it("마우스·트랙패드 기기만 좌우 넘김 버튼 자리 56px 씩을 가용 폭에서 먼저 뺀다", () => {
    const fine = fitOf(500, 800, { isFinePointer: true });
    const touch = fitOf(500, 800);

    expect(fine.scale).toBeCloseTo((500 - 112) / 360, 10);
    expect(fine.left).toBe(Math.floor(56 + (388 - fine.width) / 2));
    expect(touch.scale).toBe(PAGE_SCALE_MAX);
  });

  it("배율이 하한 밑이면 자르지 않고 그대로 낸 채 하한 밑이라고 알린다", () => {
    const fit = fitOf(844, 390);

    expect(fit.scale).toBeCloseTo((390 - 114) / 540, 10);
    expect(fit.scale).toBeLessThan(PAGE_SCALE_MIN);
    expect(fit.isBelowMinimum).toBe(true);
  });

  it("하한에 딱 맞는 배율은 하한 밑이 아니다", () => {
    expect(fitOf(360 * PAGE_SCALE_MIN, 2000).isBelowMinimum).toBe(false);
  });

  it("직전이 하한 밑이었으면 하한을 넘어도 돌아오는 배율에 닿을 때까지 하한 밑으로 둔다", () => {
    // 한 장이고 폭이 배율을 정하는 창 — 폭 / 360 이 곧 배율이다.
    const between = 360 * ((PAGE_SCALE_MIN + PAGE_SCALE_RESUME) / 2);

    expect(fitOf(between, 2000).isBelowMinimum).toBe(false);
    expect(fitOf(between, 2000, { wasBelowMinimum: true }).isBelowMinimum).toBe(true);
    expect(fitOf(360 * PAGE_SCALE_RESUME, 2000, { wasBelowMinimum: true }).isBelowMinimum).toBe(false);
  });

  it("돌아오는 배율은 iPhone SE 의 Safari 세로보다 낮다 — 가로로 눕혔다 세우면 페이지로 돌아온다", () => {
    expect(fitOf(375, 553, { wasBelowMinimum: true }).isBelowMinimum).toBe(false);
  });

  it("아직 재지 못한 0 크기 창에서도 음수나 NaN 을 내지 않는다", () => {
    const fit = fitOf(0, 0);

    expect(fit.scale).toBe(0);
    expect(fit.isBelowMinimum).toBe(true);
    expect(Number.isNaN(fit.left) || Number.isNaN(fit.top)).toBe(false);
  });
});
