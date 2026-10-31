import type { AttendanceBoard } from "@/entities/clover";

import type { ClaimErrorKind } from "./claimError";

/** 수령 결과 뒤 포커스를 옮길 곳 — 버튼 자리를 대신한 결과·안내 문장, 또는 다시 그려진 수령 버튼. */
export type ClaimFocusTarget = "message" | "button";

/** 수령 결과가 버튼 자리를 다른 것으로 바꾸는가. 바꾸면 누른 버튼이 사라져 포커스가 `<body>` 로 떨어지므로 바뀐 자리(결과·안내
 * 문장)로 포커스를 옮겨야 한다.
 *
 * 판으로 끝나면 지급 여부가 아니라 판 상태로 본다 — 다른 기기에서 이미 받은 날 누르면 지급 없이(`granted: false`) 오늘 받은
 * 판이 와서 버튼이 사라진다. 실패·잠시 멈춤은 같은 버튼을 그 자리에 그대로 두어 포커스도 그대로고, 출석이 꺼진 404 는 찾을 수
 * 없는 화면이 통째로 대신한다. */
export function claimReplacesButton(
  result: { board: Pick<AttendanceBoard, "canClaimToday"> } | { error: ClaimErrorKind },
): boolean {
  if ("board" in result) return !result.board.canClaimToday;
  return result.error === "checking" || result.error === "identity";
}
