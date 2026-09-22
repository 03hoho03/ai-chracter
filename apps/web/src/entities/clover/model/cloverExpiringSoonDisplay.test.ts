import { describe, expect, it } from "vitest";

import { formatCloverExpiringSoonMessage } from "./cloverExpiringSoonDisplay";

describe("formatCloverExpiringSoonMessage", () => {
  it("expiringSoon이 없으면 null을 돌려준다 — 화면이 안 보여줘야 할 때를 구분한다", () => {
    expect(formatCloverExpiringSoonMessage(null, new Date("2026-09-21T00:00:00Z"))).toBeNull();
  });

  it("만료까지 하루가 안 남았으면 '오늘'로 접는다", () => {
    const now = new Date("2026-09-21T00:00:00Z");
    const expiresAt = new Date("2026-09-21T12:00:00Z").toISOString(); // 12시간 뒤
    expect(formatCloverExpiringSoonMessage({ amount: 42, expiresAt }, now)).toBe(
      "클로버 42개가 오늘 소멸돼요",
    );
  });

  it("만료까지 25시간(1일 넘게) 남았으면 'N일 뒤'로 보여준다", () => {
    const now = new Date("2026-09-21T00:00:00Z");
    const expiresAt = new Date("2026-09-22T01:00:00Z").toISOString(); // 25시간 뒤
    expect(formatCloverExpiringSoonMessage({ amount: 100, expiresAt }, now)).toBe(
      "클로버 100개가 1일 뒤 소멸돼요",
    );
  });

  it("이미 지난 시각이어도 음수 D-day를 보여주지 않는다 — '오늘'로 방어적으로 접는다(BE가 이미 만료 필터를 걸어 실전엔 안 나타나지만, 순수 함수는 입력을 방어한다)", () => {
    const now = new Date("2026-09-21T12:00:00Z");
    const expiresAt = new Date("2026-09-21T00:00:00Z").toISOString(); // 12시간 전(과거)
    expect(formatCloverExpiringSoonMessage({ amount: 10, expiresAt }, now)).toBe(
      "클로버 10개가 오늘 소멸돼요",
    );
  });
});
