import type { components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { cloverKeys } from "./keys";

export type CloverAttendanceResponse = components["schemas"]["CloverAttendanceResponse"];

/** clover-goal-prompt.md CL-16 — 일일 출석 지급. **멱등은 서버가 보장한다**(BE가 유저+KST 날짜로
 * 결정적 멱등키를 만들어 원장 유니크 제약에 건다) — FE 가 "오늘 받았나"를 판단하지 않는다.
 * 그래서 중복 호출이 안전하고, `granted: false`는 오류가 아니라 "오늘 이미 받았다"는 정상 응답이다.
 *
 * 응답이 갱신된 잔액을 주지만 `setQueryData`가 아니라 **invalidate**를 쓴다 — 응답 모양
 * (`{granted, balance}`)이 잔액 쿼리의 모양(`{balance, spendConfirmedToday, attendanceClaimable}`)과
 * 달라서 부분 갱신을 하면 `attendanceClaimable`이 낡은 `true`로 남는다. */
export function useClaimAttendanceMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      apiClient.post<CloverAttendanceResponse>("/me/clover/attendance").then((res) => res.data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: cloverKeys.balance() });
    },
  });
}
