import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { noticeKeys } from "./keys";
import type { AdminNoticeDetailResponse } from "./useNoticeDetailQuery";

export type AdminNoticeUpdateRequest = components["schemas"]["AdminNoticeUpdateRequest"];

/** 성공 시 목록·상세 쿼리를 모두 무효화한다(`useModerationActionMutation` 선례). */
export function useUpdateNoticeMutation(noticeId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminNoticeDetailResponse, ApiError, AdminNoticeUpdateRequest>({
    mutationFn: async (payload) =>
      (await apiClient.patch<AdminNoticeDetailResponse>(`/admin/notices/${noticeId}`, payload)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: noticeKeys.all }),
  });
}
