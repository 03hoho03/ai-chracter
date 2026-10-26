import { describe, expect, it } from "vitest";

import { describeCloverProductLine } from "./cloverProductLine";

describe("describeCloverProductLine", () => {
  it("유료·보너스·총량을 쉼표 자리 표기로 낸다", () => {
    expect(describeCloverProductLine({ paidAmount: 49500, bonusAmount: 9900, totalAmount: 59400 })).toMatchObject({
      paid: "49,500",
      bonus: "9,900",
      total: "59,400",
    });
  });

  // 총량은 서버가 준 값이다 — 화면이 유료 + 보너스를 다시 더하면 서버와 다른 합을 보일 수 있다.
  it("총량은 두 수를 더하지 않고 받은 값을 그대로 쓴다", () => {
    expect(describeCloverProductLine({ paidAmount: 1, bonusAmount: 1, totalAmount: 5 }).total).toBe("5");
  });

  // 다섯 행이 같은 식 모양이라야 세로로 견줄 수 있다 — 보너스가 없는 상품도 항을 빼지 않는다.
  it("보너스가 0이어도 보너스 항을 남긴다", () => {
    expect(describeCloverProductLine({ paidAmount: 900, bonusAmount: 0, totalAmount: 900 })).toMatchObject({
      bonus: "0",
      spoken: "유료 클로버 900개와 보너스 0개, 모두 900개",
    });
  });

  // 화면 읽기 프로그램이 "+"·"=" 를 기호 이름으로 읽지 않게 낭독 문장은 기호 없이 말로 잇는다.
  it("낭독 문장에는 더하기·같음 기호가 없다", () => {
    const { spoken } = describeCloverProductLine({ paidAmount: 9900, bonusAmount: 990, totalAmount: 10890 });
    expect(spoken).toBe("유료 클로버 9,900개와 보너스 990개, 모두 10,890개");
    expect(spoken).not.toMatch(/[+=]/);
  });
});
