import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { appealKeys, type AppealStatusFilter } from "./keys";

export type AdminAppealListResponse = components["schemas"]["AdminAppealListResponse"];

/** techspec-admin.md §2 — 신고 목록(§1)과 동일한 전통적(offset) 페이지네이션. `status` 미지정 시 전체 조회. */
export function useAppealListQuery(params: { page: number; status?: AppealStatusFilter }) {
  return useQuery<AdminAppealListResponse, ApiError>({
    queryKey: appealKeys.list(params),
    queryFn: async () =>
      (
        await apiClient.get<AdminAppealListResponse>("/admin/appeals", {
          params: { page: params.page, status: params.status },
        })
      ).data,
  });
}
