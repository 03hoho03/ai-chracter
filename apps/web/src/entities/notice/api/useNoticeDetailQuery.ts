import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { noticeKeys } from "./keys";

export type NoticeDetailResponse = components["schemas"]["NoticeDetailResponse"];

/** `GET /notices/{id}` — 공개 조회, 인증 불필요. 미게시 공지는 404이고 재시도해도 절대
 * 성공하지 않으므로 4xx는 즉시 에러 상태로 넘긴다(entities/legal의 동일 패턴). */
export function useNoticeDetailQuery(id: string) {
  return useQuery<NoticeDetailResponse, ApiError>({
    queryKey: noticeKeys.detail(id),
    queryFn: async () => (await apiClient.get<NoticeDetailResponse>(`/notices/${id}`)).data,
    retry: (failureCount, error) => (error.status === 0 || error.status >= 500) && failureCount < 3,
  });
}
