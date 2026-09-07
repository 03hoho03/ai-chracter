import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { noticeKeys } from "./keys";

// TODO(T-11b): codegen 후 `components["schemas"]["AdminNoticeDetailResponse"]`로 교체한다.
// `packages/api-types`의 codegen이 아직 안 돌아 이 스키마가 생성되지 않았다 — BE(`api/admin/notices.py`)는
// 이미 이 모양으로 응답한다. `updatedAt`이 없는 것은 누락이 아니다: `Notice.updated_at`은
// `onupdate=func.now()`(SQL 표현식) 컬럼이라 커밋 직후 읽으면 그린렛 밖 재조회가 필요해
// 응답 스펙에서 뺐다(`_to_detail` 주석).
export type AdminNoticeDetailResponse = {
  id: string;
  title: string;
  bodyMarkdown: string;
  published: boolean;
  publishedAt: string | null;
  createdAt: string;
};

export function useNoticeDetailQuery(noticeId: string) {
  return useQuery<AdminNoticeDetailResponse, ApiError>({
    queryKey: noticeKeys.detail(noticeId),
    queryFn: async () => (await apiClient.get<AdminNoticeDetailResponse>(`/admin/notices/${noticeId}`)).data,
  });
}
