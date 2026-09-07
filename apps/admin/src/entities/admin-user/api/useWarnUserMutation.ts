import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminUserKeys } from "./keys";

export type AdminUserWarnRequest = components["schemas"]["AdminUserWarnRequest"];

/** POST /admin/users/{id}/warn — 응답 204(본문 없음). 정지 중인 유저에게도 허용된다.
 * 작품 쿼리 무효화는 호출부 몫이다(useSuspendUserMutation 주석 참고, suspend/unsuspend와 동형). */
export function useWarnUserMutation(userId: string) {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, AdminUserWarnRequest>({
    mutationFn: async (payload) => {
      await apiClient.post(`/admin/users/${userId}/warn`, payload);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminUserKeys.all }),
  });
}
