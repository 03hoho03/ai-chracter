import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminNovelKeys } from "./keys";

export type AdminNovelDetailResponse = components["schemas"]["AdminNovelDetailResponse"];

/** 공개본 글·화 목록·심사 기록·최근 신고 20개·구매 합계. */
export function useNovelDetailQuery(novelId: string) {
  return useQuery<AdminNovelDetailResponse, ApiError>({
    queryKey: adminNovelKeys.detail(novelId),
    queryFn: async () => (await apiClient.get<AdminNovelDetailResponse>(`/admin/novels/${novelId}`)).data,
  });
}
