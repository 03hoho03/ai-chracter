import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminUserKeys } from "./keys";

export type AdminUserSuspendRequest = components["schemas"]["AdminUserSuspendRequest"];
export type AdminUserSuspendResponse = components["schemas"]["AdminUserSuspendResponse"];

/** POST /admin/users/{id}/suspend — 멱등(중복 정지 400 아님). 응답의 `restrictedContentCount`로
 * 실제 이용제한으로 전환된 작품 수를 알 수 있다(호출부가 toast에 담는다). 정지는 작품 상태도
 * 바꾸지만 **작품 쿼리 무효화는 호출부 몫이다** — 여기서 `adminContentKeys`를 가져오면 entity끼리
 * 물리는 크로스 import가 된다(UserActionConfirmModal이 세 조치 뒤에 한 번에 끊는다). */
export function useSuspendUserMutation(userId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminUserSuspendResponse, ApiError, AdminUserSuspendRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminUserSuspendResponse>(`/admin/users/${userId}/suspend`, payload)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminUserKeys.all }),
  });
}
