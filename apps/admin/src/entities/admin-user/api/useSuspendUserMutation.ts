import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminContentKeys } from "@/entities/admin-content";
import { apiClient } from "@/shared/lib/api/client";
import { adminUserKeys } from "./keys";

export type AdminUserSuspendRequest = components["schemas"]["AdminUserSuspendRequest"];
export type AdminUserSuspendResponse = components["schemas"]["AdminUserSuspendResponse"];

/** POST /admin/users/{id}/suspend — 멱등(중복 정지 400 아님). 응답의 `restrictedContentCount`로
 * 실제 이용제한으로 전환된 작품 수를 알 수 있다(호출부가 toast에 담는다). 정지가 작품 상태를
 * 바꾸므로 유저·작품 쿼리를 모두 무효화한다. */
export function useSuspendUserMutation(userId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminUserSuspendResponse, ApiError, AdminUserSuspendRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminUserSuspendResponse>(`/admin/users/${userId}/suspend`, payload)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminUserKeys.all });
      void queryClient.invalidateQueries({ queryKey: adminContentKeys.all });
    },
  });
}
