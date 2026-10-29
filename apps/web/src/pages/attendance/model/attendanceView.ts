import type { AttendanceBoard } from "@/entities/clover";

import type { ClaimErrorKind } from "./claimError";
import { isReturningAfterBreak } from "./returningVisitor";

/** 수령 흐름의 지금 상태. 실패 갈래는 `classifyClaimError` 와 응답 유실 재조회 결과에서 온다. */
export type ClaimFlow = "idle" | "claiming" | ClaimErrorKind;

export type AttendanceViewInput = {
  pricing: { isPending: boolean; isError: boolean; attendanceEnabled: boolean | undefined; rewards: readonly number[] | undefined };
  session: { isPending: boolean; isLoggedIn: boolean; identityVerified: boolean };
  board: { isPending: boolean; failureCount: number; isNotFound: boolean; data: AttendanceBoard | undefined };
  claim: ClaimFlow;
  todayKst: string;
};

/** 판 아래 버튼 자리. */
export type ClaimArea =
  | { kind: "checking" }
  | { kind: "failed" }
  | { kind: "paused" }
  | { kind: "identity" }
  | { kind: "completed" }
  | { kind: "claimed"; amount: number }
  | { kind: "unavailable" }
  | { kind: "claim"; seq: number; amount: number; isClaiming: boolean };

export type AttendanceView =
  | { kind: "skeleton" }
  | { kind: "notFound" }
  | { kind: "guest"; rewards: readonly number[] }
  | { kind: "loadFailed" }
  | { kind: "board"; board: AttendanceBoard; claimArea: ClaimArea; isReturning: boolean };

/** 화면 상태 판정. 위에서 처음 맞는 줄이 이긴다.
 *
 * 판 조회 대상은 "가격 응답의 출석 스위치, 가격을 못 받았으면 서버 판 응답에 맡긴다" 다 — 노벨 목록이 가격 실패를 꺼짐으로
 * 보지 않고 목록 응답에 맡기는 것과 같은 쪽이다. 비로그인은 판을 물을 수 없고 그릴 공개 보상표도 가격 응답에 있어, 가격을
 * 못 받으면 찾을 수 없는 화면이다.
 *
 * 기다림은 판 조회 대상일 때만, 첫 실패 전까지만 센다. 꺼진 쿼리는 데이터가 없으면 `isPending` 이 늘 참이고 재시도
 * 백오프 중에도 참이라, 그대로 쓰면 꺼진 화면·실패한 화면이 영영 스켈레톤에 머문다. */
export function toAttendanceView(input: AttendanceViewInput): AttendanceView {
  const { pricing, session, board, claim, todayKst } = input;
  const shouldLoadBoard = pricing.attendanceEnabled ?? pricing.isError;

  if (
    pricing.isPending ||
    session.isPending ||
    (session.isLoggedIn && shouldLoadBoard && board.isPending && board.failureCount === 0)
  ) {
    return { kind: "skeleton" };
  }
  if (
    pricing.attendanceEnabled === false ||
    board.isNotFound ||
    claim === "off" ||
    (!session.isLoggedIn && pricing.isError)
  ) {
    return { kind: "notFound" };
  }
  if (!session.isLoggedIn) return { kind: "guest", rewards: pricing.rewards ?? [] };
  if (board.data === undefined) return { kind: "loadFailed" };

  const data = board.data;
  const claimedCount = data.cells.filter((cell) => cell.status === "claimed").length;
  const isReturning = data.canClaimToday && claimedCount >= 1 && isReturningAfterBreak(data.lastClaimedOn, todayKst);
  return { kind: "board", board: data, claimArea: toClaimArea(data, claimedCount, session.identityVerified, claim), isReturning };
}

function toClaimArea(
  board: AttendanceBoard,
  claimedCount: number,
  identityVerified: boolean,
  claim: ClaimFlow,
): ClaimArea {
  // 수령 흐름의 결과가 그 자리의 할 일이다 — 판 상태보다 먼저 본다. 인증 403 은 세션이 다시 오기 전에도 따른다.
  if (claim === "checking" || claim === "failed" || claim === "paused" || claim === "identity") return { kind: claim };
  if (board.completedToday) return { kind: "completed" };
  if (!board.canClaimToday) {
    const lastClaimed = board.cells[claimedCount - 1];
    // 받은 칸 없이 오늘 받을 수 없으면 오늘 탈퇴 전 계정에서 받은 같은 사람이다 — 이유를 말하면 탈퇴 사실이 드러난다.
    return lastClaimed === undefined ? { kind: "unavailable" } : { kind: "claimed", amount: lastClaimed.amount };
  }
  // 오늘 받음·완주·불가가 위에서 먼저 걸려, 미인증이어도 그때는 인증 안내를 띄우지 않는다.
  if (!identityVerified) return { kind: "identity" };
  const today = board.cells.find((cell) => cell.status === "today");
  // 받을 수 있다는 판에 오늘 칸이 없을 수는 없지만, 그때 없는 칸을 받으라고 하지 않는다.
  if (today === undefined) return { kind: "unavailable" };
  return { kind: "claim", seq: today.seq, amount: today.amount, isClaiming: claim === "claiming" };
}
