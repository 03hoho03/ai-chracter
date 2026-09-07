import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { inquiryKeys } from "./keys";
import type { AdminInquiryDetailResponse } from "./useInquiryDetailQuery";

export type AdminInquiryReplyRequest = components["schemas"]["AdminInquiryReplyRequest"];

/** 성공 시 문의 목록·상세 쿼리를 모두 무효화한다(`useModerationActionMutation` 선례). */
export function useReplyInquiryMutation(inquiryId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminInquiryDetailResponse, ApiError, AdminInquiryReplyRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminInquiryDetailResponse>(`/admin/inquiries/${inquiryId}/reply`, payload)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: inquiryKeys.all }),
  });
}
