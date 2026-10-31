import type { components } from "@ai-character-chat/api-types";
import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { cloverKeys } from "./keys";

export type AttendanceBoard = components["schemas"]["AttendanceBoardResponse"];
export type AttendanceCell = components["schemas"]["AttendanceCell"];
export type AttendanceClaimResponse = components["schemas"]["AttendanceClaimResponse"];

/** 로그인 회원의 출석판. 옵션을 훅 밖에 두는 이유는 수령 응답을 잃었을 때 화면이 같은 키·함수로 판을 다시 받아 지급
 * 여부를 확인해야 해서다(잔액의 `cloverBalanceQueryOptions` 와 같은 모양). `staleTime` 은 기본값이다 — 서버가 매번 오늘
 * 날짜로 판을 다시 계산하므로, 화면에 다시 들어올 때마다 새로 받아 자정을 넘긴 판이 남지 않게 한다. */
export function attendanceBoardQueryOptions() {
  return queryOptions({
    queryKey: cloverKeys.attendance(),
    queryFn: async () => (await apiClient.get<AttendanceBoard>("/me/attendance")).data,
  });
}
