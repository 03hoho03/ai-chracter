import type { AttendanceBoard } from "@/entities/clover";

import type { ClaimArea } from "./attendanceView";

/** 판의 칸 수. 서버가 늘 28칸 판을 준다. */
const BOARD_SIZE = 28;

// 출석은 하루 쉬어도 이어지는 누적 진도다. 어떤 문구에도 "연속" 을 쓰지 않는다 — 빠지면 끊긴다는 약속으로 읽힌다.

export const RETURNING_SENTENCE = "돌아오셨네요! 지난 출석에 이어서 받을 수 있어요.";

/** 천 단위 쉼표. 브라우저 언어 설정과 무관하게 같은 표기가 나오게 언어를 고정한다. */
export function formatCloverAmount(amount: number): string {
  return amount.toLocaleString("ko-KR");
}

export function formatClaimButtonLabel(seq: number, amount: number): string {
  return `${seq}일차 · ${formatCloverAmount(amount)}클로버 받기`;
}

export function formatProgress(claimedCount: number): string {
  return `${claimedCount} / ${BOARD_SIZE}일 출석 완료`;
}

/** 다음 특별 보상까지 남은 출석 수. 남은 날 수(`daysUntil`)가 아니라 칸 번호 차이로 센다 — 날짜로 말하면 매일 온다는
 * 전제를 깔아 하루라도 빠지면 틀린 문장이 된다. 오늘 받을 칸도 남은 출석 한 번으로 센다. */
export function formatNextSpecialSentence(
  board: Pick<AttendanceBoard, "cells" | "canClaimToday" | "nextSpecial">,
): string | null {
  if (board.nextSpecial === null) return null;
  const claimedCount = board.cells.filter((cell) => cell.status === "claimed").length;
  const remaining = board.nextSpecial.seq - claimedCount;
  if (remaining === 1 && board.canClaimToday) return "오늘 받으면 특별 보상이에요";
  return `다음 특별 보상까지 출석 ${remaining}번`;
}

/** 비로그인 판의 진도 줄 자리. 합은 받은 보상표에서 계산한다 — 보상표가 바뀌어도 화면 숫자가 따라간다. */
export function formatGuestTotal(rewards: readonly number[]): string {
  const total = rewards.reduce((sum, amount) => sum + amount, 0);
  return `${BOARD_SIZE}일 동안 모두 받으면 ${formatCloverAmount(total)}클로버`;
}

/** 버튼 자리에 버튼 대신 놓이는 문장들, 위에서부터. 수령 버튼(`claim`)은 `formatClaimButtonLabel` 이 맡는다. */
export function formatClaimAreaLines(area: Exclude<ClaimArea, { kind: "claim" }>): string[] {
  switch (area.kind) {
    case "checking":
      return ["지급 결과를 확인하고 있어요."];
    case "failed":
      return ["보상을 받지 못했어요. 다시 시도해 주세요."];
    case "paused":
      return ["지금은 출석 보상을 잠시 받을 수 없어요. 잠시 뒤 다시 시도해 주세요."];
    case "identity":
      // 인증 안내(`IdentityRequiredNotice`)가 문장과 버튼을 함께 맡는다.
      return [];
    case "completed":
      return ["28일 출석 완주! 내일부터 새로운 출석판이 시작돼요."];
    case "claimed":
      return [`오늘 출석 완료! ${formatCloverAmount(area.amount)}클로버를 받았어요.`, "다음 보상은 내일 00:00부터 받을 수 있어요."];
    case "unavailable":
      // 받은 칸 없이 오늘 받을 수 없는 사람은 오늘 탈퇴 전 계정에서 받은 같은 사람이다 — 이유를 말하면 그 사실이 드러난다.
      return ["오늘은 받을 수 없어요. 내일 다시 와 주세요."];
  }
}
