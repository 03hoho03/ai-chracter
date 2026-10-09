import { describe, expect, it } from "vitest";

import { formatKrw } from "./formatKrw";

describe("formatKrw", () => {
  it("천 단위마다 쉼표를 넣고 원을 붙인다", () => {
    expect(formatKrw(0)).toBe("0원");
    expect(formatKrw(999)).toBe("999원");
    expect(formatKrw(1000)).toBe("1,000원");
    expect(formatKrw(1234567)).toBe("1,234,567원");
  });

  it("음수는 부호를 숫자 앞에 둔다", () => {
    expect(formatKrw(-1234)).toBe("-1,234원");
  });
});
