import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminUserKeys } from "./keys";

export type AdminUserUnsuspendRequest = components["schemas"]["AdminUserUnsuspendRequest"];
export type AdminUserUnsuspendResponse = components["schemas"]["AdminUserUnsuspendResponse"];

/** POST /admin/users/{id}/unsuspend — 응답의 `restoredContentCount`가 정지로 이용제한됐다가 정상으로 돌아온 작품
 * 수다(신고·직접 조치로 제한된 작품은 그대로라 세지 않는다). `reasonCategory` 필드가 없다(이 액션은
 * 알림을 만들지 않는다). `adminComment`는 스키마상 optional이지만 공백만 있어도 BE가 422를 내
 * 사실상 필수다 — 호출부(UserActionConfirmModal)가 스키마로 빈 값을 막는다.
 * 해제는 작품 상태를 바꾸지만 작품 쿼리 무효화는 호출부 몫이다(useSuspendUserMutation 주석 참고). */
export function useUnsuspendUserMutation(userId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminUserUnsuspendResponse, ApiError, AdminUserUnsuspendRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminUserUnsuspendResponse>(`/admin/users/${userId}/unsuspend`, payload)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminUserKeys.all }),
  });
}
