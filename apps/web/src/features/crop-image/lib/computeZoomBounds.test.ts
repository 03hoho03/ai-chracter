import { describe, expect, it } from "vitest";

import { computeZoomBounds } from "./computeZoomBounds";

/** canvas 없이 순수 계산만 검증한다(`apps/web/vitest.config.ts`가 environment: "node") —
 * `resizeImage.test.ts`와 같은 스타일. */
describe("computeZoomBounds", () => {
  it("minZoom은 항상 1이다", () => {
    expect(computeZoomBounds({ naturalWidth: 4000, naturalHeight: 3000, aspect: 1, maxEdge: 1024 }).minZoom).toBe(1);
  });

  it("가로가 긴 원본 — 정사각(1:1) 크롭이면 짧은 변(세로)이 zoom=1 크롭의 긴 변이다", () => {
    // zoom=1 크롭 사각형: naturalWidth/naturalHeight(1.333) > aspect(1) → { w: 3000*1=3000, h: 3000 }
    // longEdge = 3000, maxZoom = 3000/1024
    const { maxZoom } = computeZoomBounds({ naturalWidth: 4000, naturalHeight: 3000, aspect: 1, maxEdge: 1024 });
    expect(maxZoom).toBeCloseTo(3000 / 1024);
  });

  it("세로가 긴 원본 — 2:3 크롭이면 원본 너비가 zoom=1 크롭의 긴 변이다", () => {
    // naturalWidth/naturalHeight(0.5) <= aspect(2/3=0.667) → { w: naturalWidth, h: naturalWidth/aspect }
    // w=1000, h=1000/(2/3)=1500 → longEdge=1500
    const { maxZoom } = computeZoomBounds({
      naturalWidth: 1000,
      naturalHeight: 2000,
      aspect: 2 / 3,
      maxEdge: 512,
    });
    expect(maxZoom).toBeCloseTo(1500 / 512);
  });

  it("비율이 정확히 일치하는 원본 — zoom=1 크롭이 원본 전체다", () => {
    // naturalWidth/naturalHeight === aspect → else 분기, w=naturalWidth=800, h=naturalWidth/aspect=600
    const { maxZoom } = computeZoomBounds({ naturalWidth: 800, naturalHeight: 600, aspect: 800 / 600, maxEdge: 400 });
    expect(maxZoom).toBeCloseTo(800 / 400);
  });

  it("원본이 목표 해상도보다 작으면 maxZoom을 1로 클램프한다", () => {
    // zoom=1 크롭의 긴 변(200) < maxEdge(1024) → 계산값 200/1024 < 1 → 1로 클램프
    const { minZoom, maxZoom } = computeZoomBounds({
      naturalWidth: 200,
      naturalHeight: 200,
      aspect: 1,
      maxEdge: 1024,
    });
    expect(maxZoom).toBe(1);
    expect(maxZoom).toBeGreaterThanOrEqual(minZoom);
  });

  it("1:1 비율", () => {
    const { maxZoom } = computeZoomBounds({ naturalWidth: 2048, naturalHeight: 1024, aspect: 1, maxEdge: 512 });
    // naturalWidth/naturalHeight(2) > aspect(1) → w=1024*1=1024, h=1024 → longEdge=1024
    expect(maxZoom).toBeCloseTo(1024 / 512);
  });

  it("2:3 비율", () => {
    const { maxZoom } = computeZoomBounds({ naturalWidth: 3000, naturalHeight: 3000, aspect: 2 / 3, maxEdge: 1024 });
    // naturalWidth/naturalHeight(1) > aspect(0.667) → w=3000*(2/3)=2000, h=3000 → longEdge=3000
    expect(maxZoom).toBeCloseTo(3000 / 1024);
  });
});
