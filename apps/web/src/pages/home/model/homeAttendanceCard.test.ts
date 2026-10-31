import { describe, expect, it } from "vitest";

import type { AttendanceBoard } from "@/entities/clover";

import { isHomeAttendancePending, toHomeAttendanceCard } from "./homeAttendanceCard";

const SPECIAL_AMOUNTS: Record<number, number> = { 7: 1600, 14: 2400, 21: 3200, 28: 4800 };

function cellStatus(seq: number, claimed: number, canClaimToday: boolean): AttendanceBoard["cells"][number]["status"] {
  if (seq <= claimed) return "claimed";
  if (seq === claimed + 1 && canClaimToday) return "today";
  return "upcoming";
}

function makeBoard({
  claimed,
  canClaimToday = true,
  completedToday = false,
}: {
  claimed: number;
  canClaimToday?: boolean;
  completedToday?: boolean;
}): AttendanceBoard {
  return {
    boardNo: 1,
    rewardVersion: 1,
    cells: Array.from({ length: 28 }, (_, index) => {
      const seq = index + 1;
      const status = cellStatus(seq, claimed, canClaimToday);
      return { seq, amount: SPECIAL_AMOUNTS[seq] ?? 800, status } as const;
    }),
    canClaimToday,
    completedToday,
    nextSpecial: null,
    lastClaimedOn: null,
  };
}

/** 출석판은 늘 열려 있어 홈은 가격 응답의 출석 스위치를 기다리지 않는다 — 세션을 기다리고, 비로그인이면 카드가 없으니
 * 기다리지 않고, 로그인이면 판만 기다린다. */
describe("isHomeAttendancePending", () => {
  const base = { isSessionPending: false, isLoggedIn: true, isPending: true };

  it("로그인했으면 판 응답을 기다린다", () => {
    expect(isHomeAttendancePending(base)).toBe(true);
    expect(isHomeAttendancePending({ ...base, isPending: false })).toBe(false);
  });

  // 비로그인 홈은 카드가 없으니 기다릴 것도 없다. 판 쿼리는 꺼져 있으면 데이터 없이 `isPending` 이 늘 참이라 그대로 쓰면
  // 비로그인 홈이 영영 기다린다.
  it("비로그인이면 판 쿼리가 기다리는 중으로 보여도 기다리지 않는다", () => {
    expect(isHomeAttendancePending({ ...base, isLoggedIn: false })).toBe(false);
  });

  it("세션을 기다리는 동안은 기다린다", () => {
    expect(isHomeAttendancePending({ ...base, isSessionPending: true, isLoggedIn: false })).toBe(true);
  });
});

/** 출석판은 늘 열려 있어 로그인 회원에게는 가격 응답의 출석 스위치를 읽지 않고도 카드가 보인다. */
describe("toHomeAttendanceCard", () => {
  const base = {
    isLoggedIn: true,
    isFiltered: false,
    board: makeBoard({ claimed: 6 }),
    identityVerified: true,
  };

  it("비로그인이면 카드가 없다", () => {
    expect(toHomeAttendanceCard({ ...base, isLoggedIn: false })).toEqual({ kind: "hidden" });
  });

  it("필터를 건 홈이면 카드가 없다", () => {
    expect(toHomeAttendanceCard({ ...base, isFiltered: true })).toEqual({ kind: "hidden" });
  });

  it("인증 회원이 오늘 받을 수 있으면 오늘 칸을 말하고 점을 단다", () => {
    expect(toHomeAttendanceCard(base)).toEqual({
      kind: "shown",
      detail: "오늘 7일차 · 1,600클로버를 받을 수 있어요",
      showDot: true,
    });
  });

  // 미인증 회원이 오늘 할 수 있는 행동은 수령이 아니라 인증이다 — 점은 수령을 가리킨다.
  it("미인증 회원은 받을 수 있는 날이어도 점이 없고 인증을 권한다", () => {
    expect(toHomeAttendanceCard({ ...base, identityVerified: false })).toEqual({
      kind: "shown",
      detail: "본인인증하고 출석 시작하기",
      showDot: false,
    });
  });

  it("오늘 받았으면 진도를 말하고 점이 없다", () => {
    expect(toHomeAttendanceCard({ ...base, board: makeBoard({ claimed: 7, canClaimToday: false }) })).toEqual({
      kind: "shown",
      detail: "7 / 28일 · 내일 또 만나요",
      showDot: false,
    });
  });

  it("오늘 완주했으면 새 판을 말하고 점이 없다", () => {
    expect(
      toHomeAttendanceCard({ ...base, board: makeBoard({ claimed: 28, canClaimToday: false, completedToday: true }) }),
    ).toEqual({ kind: "shown", detail: "28일 완주! 내일 새 출석판이 열려요", showDot: false });
  });

  it("받은 칸 없이 오늘 받을 수 없으면 진도만 말하고 점이 없다", () => {
    expect(toHomeAttendanceCard({ ...base, board: makeBoard({ claimed: 0, canClaimToday: false }) })).toEqual({
      kind: "shown",
      detail: "0 / 28일",
      showDot: false,
    });
  });

  // 판을 못 받아도 출석판으로 가는 링크는 산다.
  it("판이 없으면 보조 문장과 점 없이 카드만 보인다", () => {
    expect(toHomeAttendanceCard({ ...base, board: undefined })).toEqual({ kind: "shown", detail: null, showDot: false });
  });
});
