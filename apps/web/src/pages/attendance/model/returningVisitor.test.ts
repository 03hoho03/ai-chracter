import { describe, expect, it } from "vitest";

import { isReturningAfterBreak, toKstDateKey } from "./returningVisitor";

describe("isReturningAfterBreak", () => {
  it("받은 적이 없으면 복귀가 아니다", () => {
    expect(isReturningAfterBreak(null, "2026-10-29")).toBe(false);
  });

  it("오늘 받았으면 복귀가 아니다", () => {
    expect(isReturningAfterBreak("2026-10-29", "2026-10-29")).toBe(false);
  });

  // 하루 빠진 사람에게는 판 위 "하루 쉬어도 괜찮아요" 가 이미 말하고 있어 복귀 인사가 과하다.
  it("이틀 전에 받았으면(하루 빠짐) 복귀가 아니다", () => {
    expect(isReturningAfterBreak("2026-10-27", "2026-10-29")).toBe(false);
  });

  it("사흘 전에 받았으면(이틀 이상 빠짐) 복귀다", () => {
    expect(isReturningAfterBreak("2026-10-26", "2026-10-29")).toBe(true);
  });

  it("달이 바뀌어도 달력 일수로 센다", () => {
    expect(isReturningAfterBreak("2026-10-30", "2026-11-02")).toBe(true);
    expect(isReturningAfterBreak("2026-10-31", "2026-11-02")).toBe(false);
  });

  // 기기 시계가 늦으면 마지막 수령일이 오늘보다 뒤일 수 있다.
  it("마지막 수령일이 오늘보다 뒤면 복귀가 아니다", () => {
    expect(isReturningAfterBreak("2026-11-05", "2026-10-29")).toBe(false);
  });
});

describe("toKstDateKey", () => {
  it("한국 시각 자정 직전은 그날이다", () => {
    expect(toKstDateKey(new Date("2026-10-28T14:59:59Z"))).toBe("2026-10-28");
  });

  it("한국 시각 자정부터는 다음 날이다", () => {
    expect(toKstDateKey(new Date("2026-10-28T15:00:00Z"))).toBe("2026-10-29");
  });
});
