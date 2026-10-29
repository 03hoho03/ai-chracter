import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import type { AttendanceClaimResponse } from "./attendanceBoardQueryOptions";
import { cloverKeys } from "./keys";

export type ClaimAttendanceVariables = {
  /** 누르기 직전 판의 마지막 수령일. 서버에는 보내지 않는다 — 응답을 잃었을 때 다시 받은 판과 견줘 지급됐는지 가르는
   * 데만 쓴다. */
  lastClaimedOnBefore: string | null;
};

/** 오늘 출석 보상 받기. 하루 한 번 지급은 서버가 보장해 이미 받았으면 `granted: false`(에러 아님)이고, 그때도 돌려받은 판이
 * 오늘 상태를 말하므로 화면은 그 판을 그대로 그린다.
 *
 * 낙관적 갱신은 하지 않는다 — 지급 금액과 다음 칸은 서버가 정한다. 성공하면 받은 판으로 캐시를 바꾸고, 잔액과 내역은
 * 무효화해 다시 받는다. 잔액 응답에는 만료 임박분 같은 다른 칸이 있어 응답의 잔액 숫자로 일부만 덮으면 어긋난다.
 * 실패를 화면이 할 일로 가르는 일은 이 화면 전용이라 페이지가 맡는다. */
export function useClaimAttendanceMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (_variables: ClaimAttendanceVariables) =>
      apiClient.post<AttendanceClaimResponse>("/me/attendance/claim").then((res) => res.data),
    onSuccess: (res) => {
      queryClient.setQueryData(cloverKeys.attendance(), res.board);
      void queryClient.invalidateQueries({ queryKey: cloverKeys.balance() });
      void queryClient.invalidateQueries({ queryKey: cloverKeys.ledgers() });
    },
  });
}
