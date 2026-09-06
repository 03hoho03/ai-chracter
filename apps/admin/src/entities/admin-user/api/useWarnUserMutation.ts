import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminContentKeys } from "@/entities/admin-content";
import { apiClient } from "@/shared/lib/api/client";
import { adminUserKeys } from "./keys";

export type AdminUserWarnRequest = components["schemas"]["AdminUserWarnRequest"];

/** POST /admin/users/{id}/warn — 응답 204(본문 없음). 정지 중인 유저에게도 허용된다.
 * 유저 조치가 작품 상태를 바꿀 수 있어 유저·작품 쿼리를 모두 무효화한다(suspend/unsuspend와 동형). */
export function useWarnUserMutation(userId: string) {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, AdminUserWarnRequest>({
    mutationFn: async (payload) => {
      await apiClient.post(`/admin/users/${userId}/warn`, payload);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminUserKeys.all });
      void queryClient.invalidateQueries({ queryKey: adminContentKeys.all });
    },
  });
}
