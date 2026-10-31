import { describe, expect, it } from "vitest";

import type { AttendanceBoard } from "@/entities/clover";

import { toAttendanceView, type AttendanceViewInput, type ClaimFlow } from "./attendanceView";

const SPECIAL_AMOUNTS: Record<number, number> = { 7: 1600, 14: 2400, 21: 3200, 28: 4800 };

function cellStatus(seq: number, claimed: number, canClaimToday: boolean): AttendanceBoard["cells"][number]["status"] {
  if (seq <= claimed) return "claimed";
  if (seq === claimed + 1 && canClaimToday) return "today";
  return "upcoming";
}
const REWARDS = Array.from({ length: 28 }, (_, index) => SPECIAL_AMOUNTS[index + 1] ?? 800);

/** 받은 칸 `claimed` 개짜리 판. 오늘 받을 수 있으면 다음 칸이 오늘 칸이다. */
function makeBoard({
  claimed,
  canClaimToday = true,
  completedToday = false,
  lastClaimedOn = null,
}: {
  claimed: number;
  canClaimToday?: boolean;
  completedToday?: boolean;
  lastClaimedOn?: string | null;
}): AttendanceBoard {
  const cells = REWARDS.map((amount, index) => {
    const seq = index + 1;
    const status = cellStatus(seq, claimed, canClaimToday);
    return { seq, amount, status } as const;
  });
  const next = cells.find((cell) => cell.seq > claimed && SPECIAL_AMOUNTS[cell.seq] !== undefined);
  return {
    boardNo: 1,
    rewardVersion: 1,
    cells,
    canClaimToday,
    completedToday,
    nextSpecial: next ? { seq: next.seq, amount: next.amount, daysUntil: next.seq - claimed - 1 } : null,
    lastClaimedOn,
  };
}

const TODAY = "2026-10-29";

function makeInput({
  pricing,
  session,
  board,
  claim = "idle",
}: {
  pricing?: Partial<AttendanceViewInput["pricing"]>;
  session?: Partial<AttendanceViewInput["session"]>;
  board?: Partial<AttendanceViewInput["board"]>;
  claim?: ClaimFlow;
} = {}): AttendanceViewInput {
  return {
    pricing: { isPending: false, isError: false, rewards: REWARDS, ...pricing },
    session: { isPending: false, isLoggedIn: true, identityVerified: true, ...session },
    board: {
      isPending: false,
      failureCount: 0,
      isNotFound: false,
      data: makeBoard({ claimed: 6, lastClaimedOn: "2026-10-28" }),
      ...board,
    },
    claim,
    todayKst: TODAY,
  };
}

/** 데이터가 없는 판 쿼리. TanStack Query 에서 꺼진 쿼리도 데이터가 없으면 `isPending` 이 참이다. */
const NO_BOARD = { isPending: true, failureCount: 0, isNotFound: false, data: undefined };

function claimAreaOf(input: AttendanceViewInput) {
  const view = toAttendanceView(input);
  if (view.kind !== "board") throw new Error(`expected board, got ${view.kind}`);
  return view.claimArea;
}

function isReturningOf(input: AttendanceViewInput) {
  const view = toAttendanceView(input);
  if (view.kind !== "board") throw new Error(`expected board, got ${view.kind}`);
  return view.isReturning;
}

/** 출석판은 늘 열려 있어 가격 응답의 출석 스위치를 읽지 않는다. 로그인 회원은 늘 판을 묻고, 찾을 수 없음은 판 응답의 404
 * 로만 정한다. */
describe("toAttendanceView — 기다림", () => {
  it("가격을 기다리는 동안은 스켈레톤이다", () => {
    expect(toAttendanceView(makeInput({ pricing: { isPending: true, rewards: undefined }, board: NO_BOARD }))).toEqual({
      kind: "skeleton",
    });
  });

  // 로그인 여부를 모르면 비로그인 판과 회원 판 중 무엇을 그릴지 모른다.
  it("세션을 기다리는 동안은 스켈레톤이다", () => {
    expect(toAttendanceView(makeInput({ session: { isPending: true, isLoggedIn: false }, board: NO_BOARD }))).toEqual({
      kind: "skeleton",
    });
  });

  it("로그인했으면 가격 응답의 출석 스위치 없이도 첫 판 응답을 스켈레톤으로 기다린다", () => {
    expect(toAttendanceView(makeInput({ board: NO_BOARD }))).toEqual({ kind: "skeleton" });
  });

  // 재시도 백오프 중에도 `isPending` 이 참이다 — 첫 실패 뒤에는 기다리지 않고 실패를 보인다.
  it("판이 한 번 실패한 뒤 재시도 중이면 스켈레톤이 아니라 불러오지 못함이다", () => {
    expect(toAttendanceView(makeInput({ board: { ...NO_BOARD, failureCount: 1 } }))).toEqual({ kind: "loadFailed" });
  });
});

describe("toAttendanceView — 가격 실패", () => {
  const PRICING_FAILED = { isError: true, rewards: undefined };

  // 비로그인은 판을 물을 수 없고 그릴 공개 보상표도 가격 응답에 있다.
  it("비로그인이 가격을 못 받으면 찾을 수 없음이다", () => {
    expect(
      toAttendanceView(makeInput({ pricing: PRICING_FAILED, session: { isLoggedIn: false }, board: { ...NO_BOARD, isPending: true } })),
    ).toEqual({ kind: "notFound" });
  });

  // 로그인 회원은 가격이 실패해도 판 응답이 정한다.
  it("로그인 회원은 가격을 못 받아도 판을 받으면 판을 그린다", () => {
    expect(toAttendanceView(makeInput({ pricing: PRICING_FAILED })).kind).toBe("board");
  });

  it("로그인 회원이 가격을 못 받고 판이 404 면 찾을 수 없음이다", () => {
    expect(
      toAttendanceView(
        makeInput({ pricing: PRICING_FAILED, board: { isPending: false, failureCount: 1, isNotFound: true, data: undefined } }),
      ),
    ).toEqual({ kind: "notFound" });
  });

  it("로그인 회원이 가격을 못 받으면 판 응답을 스켈레톤으로 기다린다", () => {
    expect(toAttendanceView(makeInput({ pricing: PRICING_FAILED, board: NO_BOARD }))).toEqual({ kind: "skeleton" });
  });
});

describe("toAttendanceView — 줄 순서", () => {
  it("비로그인이면 공개 보상표로 판을 그린다", () => {
    expect(toAttendanceView(makeInput({ session: { isLoggedIn: false, identityVerified: false }, board: NO_BOARD }))).toEqual({
      kind: "guest",
      rewards: REWARDS,
    });
  });

  it("판이 404 면 찾을 수 없음이다", () => {
    expect(
      toAttendanceView(makeInput({ board: { isPending: false, failureCount: 1, isNotFound: true, data: undefined } })),
    ).toEqual({ kind: "notFound" });
  });

  // 판이 없으면 그 아래 어떤 줄도 판정할 수 없다.
  it("판을 못 받았으면 미인증이어도 인증 안내가 아니라 불러오지 못함이다", () => {
    expect(
      toAttendanceView(
        makeInput({
          session: { identityVerified: false },
          board: { isPending: false, failureCount: 3, isNotFound: false, data: undefined },
        }),
      ),
    ).toEqual({ kind: "loadFailed" });
  });

  it("판을 들고 있는 채 다시 받기만 실패했으면 그 판을 그린다", () => {
    expect(toAttendanceView(makeInput({ board: { failureCount: 2 } })).kind).toBe("board");
  });
});

describe("toAttendanceView — 수령 흐름", () => {
  it("응답을 잃어 확인하는 중이면 확인 중이다", () => {
    expect(claimAreaOf(makeInput({ claim: "checking" }))).toEqual({ kind: "checking" });
  });

  it("확정 실패면 실패다", () => {
    expect(claimAreaOf(makeInput({ claim: "failed" }))).toEqual({ kind: "failed" });
  });

  it("정지 스위치면 잠시 멈춤이다", () => {
    expect(claimAreaOf(makeInput({ claim: "paused" }))).toEqual({ kind: "paused" });
  });

  // 서버가 방금 미인증이라고 답했다 — 세션이 다시 오기 전에도 그 답을 따른다.
  it("수령이 인증 403 을 받았으면 세션이 아직 인증됨이어도 인증 안내다", () => {
    expect(claimAreaOf(makeInput({ session: { identityVerified: true }, claim: "identity" }))).toEqual({ kind: "identity" });
  });

  it("수령이 404 를 받았으면 찾을 수 없음이다", () => {
    expect(toAttendanceView(makeInput({ claim: "off" }))).toEqual({ kind: "notFound" });
  });

  it("수령 중이면 수령 버튼이 진행 중이다", () => {
    expect(claimAreaOf(makeInput({ claim: "claiming" }))).toEqual({ kind: "claim", seq: 7, amount: 1600, isClaiming: true });
  });

  it("수령 흐름의 결과가 판 상태보다 먼저다", () => {
    expect(
      claimAreaOf(makeInput({ board: { data: makeBoard({ claimed: 7, canClaimToday: false }) }, claim: "failed" })),
    ).toEqual({ kind: "failed" });
  });
});

describe("toAttendanceView — 판 상태", () => {
  it("오늘 28칸째를 받았으면 완주다 — 미인증이어도 인증 안내를 띄우지 않는다", () => {
    expect(
      claimAreaOf(
        makeInput({
          session: { identityVerified: false },
          board: { data: makeBoard({ claimed: 28, canClaimToday: false, completedToday: true }) },
        }),
      ),
    ).toEqual({ kind: "completed" });
  });

  it("오늘 받았으면 마지막 받은 칸의 금액으로 받음이다 — 미인증이어도 인증 안내를 띄우지 않는다", () => {
    expect(
      claimAreaOf(
        makeInput({ session: { identityVerified: false }, board: { data: makeBoard({ claimed: 7, canClaimToday: false }) } }),
      ),
    ).toEqual({ kind: "claimed", amount: 1600 });
  });

  // 오늘 탈퇴 전 계정에서 받은 같은 사람이다 — 이유를 말하면 탈퇴 사실이 드러난다.
  it("받은 칸이 없는데 오늘 받을 수 없으면 이유 없이 불가다", () => {
    expect(claimAreaOf(makeInput({ board: { data: makeBoard({ claimed: 0, canClaimToday: false }) } }))).toEqual({
      kind: "unavailable",
    });
  });

  it("받을 수 있는데 미인증이면 인증 안내다", () => {
    expect(claimAreaOf(makeInput({ session: { identityVerified: false } }))).toEqual({ kind: "identity" });
  });

  it("받을 수 있고 인증했으면 오늘 칸의 번호와 금액으로 수령 버튼이다", () => {
    expect(claimAreaOf(makeInput())).toEqual({ kind: "claim", seq: 7, amount: 1600, isClaiming: false });
  });
});

describe("toAttendanceView — 복귀 문장", () => {
  it("마지막 수령이 사흘 이상 전이고 이어 받을 칸이 있으면 복귀 문장을 낸다", () => {
    expect(isReturningOf(makeInput({ board: { data: makeBoard({ claimed: 6, lastClaimedOn: "2026-10-26" }) } }))).toBe(true);
  });

  it("어제 받았으면 복귀 문장이 없다", () => {
    expect(isReturningOf(makeInput({ board: { data: makeBoard({ claimed: 6, lastClaimedOn: "2026-10-28" }) } }))).toBe(false);
  });

  // 28칸을 끝낸 뒤 오래 쉬고 온 사람은 새 판인데 마지막 수령일이 지난 판 날짜다 — 그 판에는 이어서 받을 것이 없다.
  it("받은 칸이 없는 새 판은 마지막 수령일이 오래됐어도 복귀 문장이 없다", () => {
    expect(isReturningOf(makeInput({ board: { data: makeBoard({ claimed: 0, lastClaimedOn: "2026-09-01" }) } }))).toBe(false);
  });

  it("미인증이어도 복귀 날짜면 인증 안내와 복귀 문장이 함께 나온다", () => {
    const view = toAttendanceView(
      makeInput({ session: { identityVerified: false }, board: { data: makeBoard({ claimed: 6, lastClaimedOn: "2026-10-20" }) } }),
    );
    expect(view).toMatchObject({ kind: "board", claimArea: { kind: "identity" }, isReturning: true });
  });

  it("오늘 받을 수 없으면 복귀 문장이 없다", () => {
    expect(
      isReturningOf(makeInput({ board: { data: makeBoard({ claimed: 6, canClaimToday: false, lastClaimedOn: "2026-10-20" }) } })),
    ).toBe(false);
  });
});
