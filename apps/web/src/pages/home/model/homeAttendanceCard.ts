import type { AttendanceBoard } from "@/entities/clover";

/** 홈 출석 카드를 기다리는가. 세션을 기다리고, 비로그인이면 카드가 없으니 기다리지 않고, 로그인이면 판을 기다린다. 판
 * 쿼리는 비로그인이라 꺼져 있어도 데이터가 없으면 `isPending` 이 늘 참이라 로그인 여부와 함께 본다 — 그대로 쓰면 비로그인
 * 홈이 영영 기다린다. */
export function isHomeAttendancePending(input: {
  isSessionPending: boolean;
  isLoggedIn: boolean;
  isPending: boolean;
}): boolean {
  if (input.isSessionPending) return true;
  return input.isLoggedIn && input.isPending;
}

export type HomeAttendanceCard = { kind: "hidden" } | { kind: "shown"; detail: string | null; showDot: boolean };

/** 홈의 출석판 진입 카드. 로그인 회원에게만 보인다 — 비로그인 홈은 판을 물을 수 없다. 판을 못 받아도 출석판으로 가는
 * 링크는 살린다.
 *
 * 점은 "오늘 할 수 있는 행동이 있다" 는 표시라 인증 회원이 받을 수 있는 날에만 단다. 미인증 회원이 오늘 할 수 있는 행동은
 * 수령이 아니라 인증이고, 보조 문장이 그것을 권한다. */
export function toHomeAttendanceCard(input: {
  isLoggedIn: boolean;
  isFiltered: boolean;
  /** 판 응답. 기다리는 중이거나 실패했으면 undefined. */
  board: AttendanceBoard | undefined;
  identityVerified: boolean;
}): HomeAttendanceCard {
  if (!input.isLoggedIn || input.isFiltered) return { kind: "hidden" };
  const { board } = input;
  if (board === undefined) return { kind: "shown", detail: null, showDot: false };
  if (board.completedToday) return { kind: "shown", detail: "28일 완주! 내일 새 출석판이 열려요", showDot: false };

  const claimedCount = board.cells.filter((cell) => cell.status === "claimed").length;
  const today = board.cells.find((cell) => cell.status === "today");
  if (board.canClaimToday && today !== undefined) {
    if (!input.identityVerified) return { kind: "shown", detail: "본인인증하고 출석 시작하기", showDot: false };
    return {
      kind: "shown",
      detail: `오늘 ${today.seq}일차 · ${today.amount.toLocaleString("ko-KR")}클로버를 받을 수 있어요`,
      showDot: true,
    };
  }
  const progress = `${claimedCount} / ${board.cells.length}일`;
  return { kind: "shown", detail: claimedCount >= 1 ? `${progress} · 내일 또 만나요` : progress, showDot: false };
}
