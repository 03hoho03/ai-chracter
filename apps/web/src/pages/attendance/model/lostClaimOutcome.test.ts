import { afterEach, describe, expect, it, vi } from "vitest";

import { lostClaimOutcome } from "./lostClaimOutcome";

afterEach(() => {
  vi.useRealTimers();
});

describe("lostClaimOutcome", () => {
  it("다시 받은 판의 마지막 수령일이 누르기 전과 달라졌으면 지급된 것이다", () => {
    expect(lostClaimOutcome("2026-10-27", { lastClaimedOn: "2026-10-28" })).toBe("granted");
  });

  it("마지막 수령일이 누르기 전과 같으면 지급되지 않은 것이다", () => {
    expect(lostClaimOutcome("2026-10-27", { lastClaimedOn: "2026-10-27" })).toBe("notGranted");
  });

  it("처음 받는 사람은 마지막 수령일이 비어 있다가 생기면 지급된 것이다", () => {
    expect(lostClaimOutcome(null, { lastClaimedOn: "2026-10-28" })).toBe("granted");
  });

  it("다시 받은 판에도 마지막 수령일이 없으면 지급되지 않은 것이다", () => {
    expect(lostClaimOutcome(null, { lastClaimedOn: null })).toBe("notGranted");
  });

  // 28칸째를 받은 뒤 자정을 넘겨 다시 받으면 새 판(받은 칸 0, 판 번호 +1)이 열려 그 칸이 판에 없다. 마지막 수령일은
  // 지난 판의 마지막 날로 남으므로 칸이나 판 번호가 아니라 그 날짜로 본다.
  it("28칸째를 누른 뒤 자정을 넘겨 새 판이 왔어도 마지막 수령일이 바뀌었으면 지급된 것이다", () => {
    const nextBoard = {
      boardNo: 2,
      rewardVersion: 1,
      cells: Array.from({ length: 28 }, (_, index) => ({
        seq: index + 1,
        amount: 800,
        status: index === 0 ? ("today" as const) : ("upcoming" as const),
      })),
      canClaimToday: true,
      completedToday: false,
      nextSpecial: { seq: 7, amount: 1600, daysUntil: 6 },
      lastClaimedOn: "2026-10-28",
    };
    expect(lostClaimOutcome("2026-10-27", nextBoard)).toBe("granted");
  });

  // 기기 시계로 오늘을 세면 자정 언저리에 누르거나 시계가 틀린 기기에서 판정이 뒤집힌다 — 판정은 두 판의 값만 본다.
  it("기기 시계가 틀려도 판정이 같다", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2031-01-01T00:00:00Z"));
    expect(lostClaimOutcome("2026-10-27", { lastClaimedOn: "2026-10-28" })).toBe("granted");
    expect(lostClaimOutcome("2026-10-27", { lastClaimedOn: "2026-10-27" })).toBe("notGranted");
  });
});
