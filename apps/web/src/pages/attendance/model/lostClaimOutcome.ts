import type { AttendanceBoard } from "@/entities/clover";

/** 응답을 잃은 수령이 실제로 지급됐는가. 누르기 직전 판의 마지막 수령일과 다시 받은 판의 마지막 수령일이 다르면 그 사이
 * 지급이 일어난 것이다.
 *
 * 칸 번호나 판 번호로 보지 않는 이유: 28칸째를 받은 뒤 자정을 넘겨 다시 받으면 새 판이 열려 그 칸이 판에 없지만, 마지막
 * 수령일은 지급한 날로 바뀌어 남는다. 기기 시계로 오늘을 세지도 않는다 — 자정 언저리에 누르거나 시계가 틀린 기기에서
 * 판정이 뒤집히므로, 두 판이 서버에서 온 값만 견준다. */
export function lostClaimOutcome(
  lastClaimedOnBefore: string | null,
  board: Pick<AttendanceBoard, "lastClaimedOn">,
): "granted" | "notGranted" {
  return board.lastClaimedOn !== null && board.lastClaimedOn !== lastClaimedOnBefore ? "granted" : "notGranted";
}
