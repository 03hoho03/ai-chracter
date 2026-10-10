import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminUserKeys } from "@/entities/admin-user";
import { apiClient } from "@/shared/lib/api/client";

export type AdminPayeeInfoViewRequest = components["schemas"]["AdminPayeeInfoViewRequest"];
export type AdminPayeeInfoViewResponse = components["schemas"]["AdminPayeeInfoViewResponse"];

/**
 * 지급 정보 원문 열람. 호출 1회 = 서버 감사 1행이라 자동 재시도하지 않는다(`useMutation` 기본이 재시도 없음).
 *
 * 원문은 쿼리 캐시에 두지 않고 호출부의 지역 상태만 쥔다 — 화면을 떠나면 사라져야 한다. 뮤테이션도 결과(`data`)를 들고
 * 있으므로 호출부가 받은 즉시 `reset` 하고, 화면이 사라지면 `gcTime: 0` 으로 기본 5분을 기다리지 않고 버린다.
 *
 * 성공하면 유저 쿼리를 끊는다 — 이 열람이 그 회원의 조치 이력에 "크리에이터 지급 정보 열람"으로 남는다.
 */
export function useViewPayeeInfoMutation(payoutId: string) {
  const queryClient = useQueryClient();
  return useMutation<AdminPayeeInfoViewResponse, ApiError, AdminPayeeInfoViewRequest>({
    mutationFn: async (body) =>
      (
        await apiClient.post<AdminPayeeInfoViewResponse>(
          `/admin/creator-payout/payouts/${encodeURIComponent(payoutId)}/payee-info-view`,
          body,
        )
      ).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminUserKeys.all }),
    gcTime: 0,
  });
}
