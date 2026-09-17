import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminUserKeys } from "./keys";

export type AdminUserRateLimitExemptRequest = components["schemas"]["AdminUserRateLimitExemptRequest"];

/** POST /admin/users/{id}/rate-limit-exempt — 응답 204(본문 없음). limit-goal-prompt.md RL-9:
 * `users.rate_limit_exempt`를 바꾸는 유일한 경로이고, 켜기·끄기를 `exempt` 한 필드로 받는 토글이다.
 * `adminComment`는 스키마상 optional이지만 공백만 있어도 BE가 422를 내 사실상 필수다 —
 * 호출부(UserActionConfirmModal)가 스키마로 빈 값을 막는다(useUnsuspendUserMutation과 같은 규칙).
 * 작품 상태를 건드리지 않아 작품 쿼리는 끊을 게 없다. */
export function useSetRateLimitExemptMutation(userId: string) {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, AdminUserRateLimitExemptRequest>({
    mutationFn: async (payload) => {
      await apiClient.post(`/admin/users/${userId}/rate-limit-exempt`, payload);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminUserKeys.all }),
  });
}
