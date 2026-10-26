import { describe, expect, it } from "vitest";

import { formatImageCostHint, imageRequestCloverCost, isImageCloverShort } from "./imageCloverCost";

describe("이미지 클로버 단가", () => {
  it("서버 단가로 한 장도 못 만드는지 판정한다", () => {
    expect(isImageCloverShort(89, 90)).toBe(true);
    expect(isImageCloverShort(90, 90)).toBe(false);
  });

  it("단가를 아직 못 받았거나 받지 못했으면 부족하다고 하지 않는다", () => {
    expect(isImageCloverShort(0, undefined)).toBe(false);
  });

  it("요청 금액은 장수 × 서버 단가이고, 단가를 모르면 금액도 모른다", () => {
    expect(imageRequestCloverCost(2, 90)).toBe(180);
    expect(imageRequestCloverCost(2, undefined)).toBeUndefined();
  });

  it("생성 버튼 옆 안내는 무료 생성 횟수가 모자랄 때의 총액이고, 여러 장이면 장당 가격을 덧붙인다", () => {
    expect(formatImageCostHint(1, 90)).toBe("무료 생성 횟수가 모자라면 클로버 90개");
    expect(formatImageCostHint(4, 90)).toBe("무료 생성 횟수가 모자라면 클로버 360개 · 장당 90개");
    expect(formatImageCostHint(2, 1500)).toBe("무료 생성 횟수가 모자라면 클로버 3,000개 · 장당 1,500개");
  });

  it("단가를 아직 못 받았거나 받지 못했으면 생성 버튼 옆 안내를 숨긴다", () => {
    expect(formatImageCostHint(4, undefined)).toBeUndefined();
  });
});
