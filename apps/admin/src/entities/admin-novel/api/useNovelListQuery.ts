import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminNovelKeys, type AdminNovelListParams } from "./keys";

export type AdminNovelListResponse = components["schemas"]["AdminNovelListResponse"];

/** 공개한 적 있는 노벨 전부(거둔 것·이용제한된 것 포함), 마지막 공개 최신순 20개씩. 서버에 이름 검색이 없어 상태로만 거른다. */
export function useNovelListQuery(params: AdminNovelListParams) {
  return useQuery<AdminNovelListResponse, ApiError>({
    queryKey: adminNovelKeys.list(params),
    queryFn: async () =>
      (
        await apiClient.get<AdminNovelListResponse>("/admin/novels", {
          params: { page: params.page, moderationStatus: params.moderationStatus },
        })
      ).data,
  });
}
