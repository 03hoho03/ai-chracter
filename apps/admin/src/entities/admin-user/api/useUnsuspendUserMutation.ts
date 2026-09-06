import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminContentKeys } from "@/entities/admin-content";
import { apiClient } from "@/shared/lib/api/client";
import { adminUserKeys } from "./keys";

export type AdminUserUnsuspendRequest = components["schemas"]["AdminUserUnsuspendRequest"];

/** POST /admin/users/{id}/unsuspend — 응답 204(본문 없음). `reasonCategory` 필드가 없다(이 액션은
 * 알림을 만들지 않는다). `adminComment`는 스키마상 optional이지만 공백만 있어도 BE가 422를 내
 * 사실상 필수다 — 호출부(UserActionConfirmModal)가 trim 후 빈 값이면 확정 버튼을 막는다.
 * 해제해도 작품은 restricted로 남으므로 작품 쿼리도 함께 무효화한다. */
export function useUnsuspendUserMutation(userId: string) {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, AdminUserUnsuspendRequest>({
    mutationFn: async (payload) => {
      await apiClient.post(`/admin/users/${userId}/unsuspend`, payload);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminUserKeys.all });
      void queryClient.invalidateQueries({ queryKey: adminContentKeys.all });
    },
  });
}
