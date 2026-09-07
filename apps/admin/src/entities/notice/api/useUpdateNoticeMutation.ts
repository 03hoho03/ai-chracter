import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { noticeKeys } from "./keys";
import type { AdminNoticeDetailResponse } from "./useNoticeDetailQuery";

// TODO(T-11b): codegen 후 `components["schemas"]["AdminNoticeUpdateRequest"]`로 교체한다.
export type AdminNoticeUpdateRequest = {
  title?: string;
  bodyMarkdown?: string;
};

/** 성공 시 목록·상세 쿼리를 모두 무효화한다(`useModerationActionMutation` 선례). */
export function useUpdateNoticeMutation(noticeId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminNoticeDetailResponse, ApiError, AdminNoticeUpdateRequest>({
    mutationFn: async (payload) =>
      (await apiClient.patch<AdminNoticeDetailResponse>(`/admin/notices/${noticeId}`, payload)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: noticeKeys.all }),
  });
}
