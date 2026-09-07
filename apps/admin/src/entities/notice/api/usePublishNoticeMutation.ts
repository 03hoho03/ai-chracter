import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { noticeKeys } from "./keys";
import type { AdminNoticeDetailResponse } from "./useNoticeDetailQuery";

/** 게시 — 전이일 때만 알림 fan-out이 일어난다(BE, techspec.md §6-2/D-16). 성공 시 목록·상세
 * 쿼리를 모두 무효화한다(`useModerationActionMutation` 선례). */
export function usePublishNoticeMutation(noticeId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminNoticeDetailResponse, ApiError, void>({
    mutationFn: async () =>
      (await apiClient.post<AdminNoticeDetailResponse>(`/admin/notices/${noticeId}/publish`)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: noticeKeys.all }),
  });
}

/** 숨김 — `published_at`은 유지된다(재게시 시 최초 게시일이 살아남는다). */
export function useUnpublishNoticeMutation(noticeId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminNoticeDetailResponse, ApiError, void>({
    mutationFn: async () =>
      (await apiClient.post<AdminNoticeDetailResponse>(`/admin/notices/${noticeId}/unpublish`)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: noticeKeys.all }),
  });
}
