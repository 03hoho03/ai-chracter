import { describe, expect, it } from "vitest";

import { formatMs, formatUsd } from "./formatNumber";

describe("formatUsd", () => {
  it("소수 넷째 자리까지, 천 단위 쉼표", () => {
    expect(formatUsd(0.0912)).toBe("$0.0912");
    expect(formatUsd(2.41874)).toBe("$2.4187");
    expect(formatUsd(1234.5)).toBe("$1,234.5000");
  });

  it("0 원도 같은 자릿수로 적는다 — 원가가 없는 것과는 다른 모양이다", () => {
    expect(formatUsd(0)).toBe("$0.0000");
  });
});

describe("formatMs", () => {
  it("ms 정수에 천 단위 쉼표", () => {
    expect(formatMs(2140)).toBe("2,140ms");
    expect(formatMs(87.6)).toBe("88ms");
  });
});
