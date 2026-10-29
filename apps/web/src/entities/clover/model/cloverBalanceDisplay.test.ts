import { describe, expect, it } from "vitest";

import { isCloverInsufficient, shouldShowCloverBalance } from "./cloverBalanceDisplay";

describe("shouldShowCloverBalance", () => {
  // "필요할 때만 노출"의 본체. 둘 다 거짓인 조합이 **유일하게**
  // 숨기는 조합이라, 이 케이스가 빠지면 "항상 보인다"로 바뀌어도 나머지가 전부 통과한다.
  it("무료분을 아직 쓰지 않았고 부족하지도 않으면 숨긴다", () => {
    expect(shouldShowCloverBalance({ spendConfirmedToday: false, hasCloverShortage: false })).toBe(false);
  });

  it("오늘 차감을 확인했으면 보여준다 — 그게 소진 이후에만 참이 되는 신호다", () => {
    expect(shouldShowCloverBalance({ spendConfirmedToday: true, hasCloverShortage: false })).toBe(true);
  });

  // 확인 기록보다 부족이 앞선다 — 확인을 누르기 전에 잔액이 0일 수 있다.
  it("확인 전이라도 부족하면 보여준다", () => {
    expect(shouldShowCloverBalance({ spendConfirmedToday: false, hasCloverShortage: true })).toBe(true);
  });
});

describe("isCloverInsufficient", () => {
  // 🔴 `balance === 0`으로 짜면 이 케이스만 빨개진다 — 0이 아닌데 못 내는 구간이
  // 이 함수의 존재 이유다(이미지 30 vs 잔액 10).
  it("0이 아니어도 단가를 못 내면 부족이다", () => {
    expect(isCloverInsufficient(10, 30)).toBe(true);
  });

  it("딱 맞으면 부족이 아니다", () => {
    expect(isCloverInsufficient(30, 30)).toBe(false);
  });

  it("남으면 부족이 아니다", () => {
    expect(isCloverInsufficient(100, 10)).toBe(false);
  });

  it("0은 어떤 단가에서도 부족이다", () => {
    expect(isCloverInsufficient(0, 10)).toBe(true);
  });
});
