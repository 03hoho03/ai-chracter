import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminContentKeys, type AdminContentListParams } from "./keys";

export type AdminContentListResponse = components["schemas"]["AdminContentListResponse"];

/** techspec.md §4-2 — offset 페이지네이션(20건), 필터 3종·이름 검색·정렬 3종. */
export function useContentListQuery(params: AdminContentListParams) {
  return useQuery<AdminContentListResponse, ApiError>({
    queryKey: adminContentKeys.list(params),
    queryFn: async () =>
      (
        await apiClient.get<AdminContentListResponse>("/admin/contents", {
          params: {
            page: params.page,
            type: params.type,
            visibility: params.visibility,
            moderationStatus: params.moderationStatus,
            q: params.q,
            sort: params.sort,
          },
        })
      ).data,
  });
}
