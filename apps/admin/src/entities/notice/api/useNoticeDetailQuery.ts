import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { noticeKeys } from "./keys";

// `updatedAt`이 없는 것은 누락이 아니다: `Notice.updated_at`은 `onupdate=func.now()`(SQL 표현식)
// 컬럼이라 커밋 직후 읽으면 그린렛 밖 재조회가 필요해 응답 스펙에서 뺐다(`_to_detail` 주석).
export type AdminNoticeDetailResponse = components["schemas"]["AdminNoticeDetailResponse"];

export function useNoticeDetailQuery(noticeId: string) {
  return useQuery<AdminNoticeDetailResponse, ApiError>({
    queryKey: noticeKeys.detail(noticeId),
    queryFn: async () => (await apiClient.get<AdminNoticeDetailResponse>(`/admin/notices/${noticeId}`)).data,
  });
}
