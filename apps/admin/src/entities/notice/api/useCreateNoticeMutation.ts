import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { noticeKeys } from "./keys";
import type { AdminNoticeDetailResponse } from "./useNoticeDetailQuery";

export type AdminNoticeCreateRequest = components["schemas"]["AdminNoticeCreateRequest"];

/** 생성은 `published=false`로 시작한다(BE). 성공 시 목록 쿼리를 무효화한다(`useModerationActionMutation` 선례). */
export function useCreateNoticeMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminNoticeDetailResponse, ApiError, AdminNoticeCreateRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminNoticeDetailResponse>("/admin/notices", payload)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: noticeKeys.all }),
  });
}
