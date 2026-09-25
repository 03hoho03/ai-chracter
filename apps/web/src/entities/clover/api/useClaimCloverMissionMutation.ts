import type { components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { cloverKeys } from "./keys";

export type CloverMissionClaimResponse = components["schemas"]["CloverMissionClaimResponse"];

/** 미션 청구. 멱등은 서버가 보장한다(`mission:{user_id}:{key}`
 * 원장 유니크 제약) — 이미 청구했으면 `granted: false`이고 **에러가 아니다**
 * (`useClaimAttendanceMutation`과 같은 규칙).
 *
 * 성공 시 잔액과 미션 목록 둘 다 invalidate한다 — 미션 쿼리는 `claimed`가 저장된 상태가 아니라
 * 원장 EXISTS 재판정이라, invalidate하지 않으면 방금 청구한 미션이 화면에서 계속
 * "받기" 상태로 보인다. */
export function useClaimCloverMissionMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (key: string) =>
      apiClient
        .post<CloverMissionClaimResponse>(`/me/clover/missions/${key}/claim`)
        .then((res) => res.data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: cloverKeys.balance() });
      void queryClient.invalidateQueries({ queryKey: cloverKeys.missions() });
    },
  });
}
