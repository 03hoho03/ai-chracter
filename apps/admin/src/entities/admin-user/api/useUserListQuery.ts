import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminUserKeys, type AdminUserListParams } from "./keys";

export type AdminUserListResponse = components["schemas"]["AdminUserListResponse"];

/** GET /admin/users — offset 페이지네이션(20건), q(이메일·닉네임 ILIKE OR)·suspended 필터.
 * `sort` 파라미터는 BE에 없다 — 만들지 않는다. 탈퇴 유저는 BE가 항상 제외한다. */
export function useUserListQuery(params: AdminUserListParams) {
  return useQuery<AdminUserListResponse, ApiError>({
    queryKey: adminUserKeys.list(params),
    queryFn: async () =>
      (
        await apiClient.get<AdminUserListResponse>("/admin/users", {
          params: { page: params.page, q: params.q, suspended: params.suspended },
        })
      ).data,
  });
}
