import { describe, expect, it } from "vitest";

import { formatCompactCount } from "./formatCompactCount";

describe("formatCompactCount", () => {
  it("returns 0", () => {
    expect(formatCompactCount(0)).toBe("0");
  });

  it("returns full digits under 1000 (no compaction)", () => {
    expect(formatCompactCount(5)).toBe("5");
    expect(formatCompactCount(999)).toBe("999");
  });

  it("compacts at the 1000 boundary", () => {
    expect(formatCompactCount(1000)).toBe("1K");
  });

  it("keeps one fraction digit for mid-range values", () => {
    expect(formatCompactCount(1234)).toBe("1.2K");
    expect(formatCompactCount(46_821)).toBe("46.8K");
  });

  // maximumFractionDigits: 1 rounds 9999 up to the next unit — 9999와 10000이 같은 문자열을 낸다.
  // "Intl이 알아서 반올림한다"가 아니라 우리가 고른 정밀도(소수 1자리)가 이 경계에서 둘을 구분하지
  // 못한다는 게 검증 대상이다.
  it("rounds 9999 up to 10K, matching the 10000 boundary", () => {
    expect(formatCompactCount(9999)).toBe("10K");
    expect(formatCompactCount(10_000)).toBe("10K");
  });

  it("compacts to M at the 1,000,000 boundary", () => {
    expect(formatCompactCount(1_000_000)).toBe("1M");
    expect(formatCompactCount(1_234_567)).toBe("1.2M");
  });

  // 같은 이유로 999999도 1M로 반올림된다 — K/M 경계 바로 아래 값이 다음 단위로 넘어가는 것도 정밀도의
  // 결과이지 우연이 아니다.
  it("rounds 999999 up to 1M, matching the 1000000 boundary", () => {
    expect(formatCompactCount(999_999)).toBe("1M");
  });
});
