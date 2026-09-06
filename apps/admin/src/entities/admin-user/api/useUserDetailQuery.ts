import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { adminUserKeys } from "./keys";

export type AdminUserDetailResponse = components["schemas"]["AdminUserDetailResponse"];

export function useUserDetailQuery(userId: string) {
  return useQuery<AdminUserDetailResponse, ApiError>({
    queryKey: adminUserKeys.detail(userId),
    queryFn: async () => (await apiClient.get<AdminUserDetailResponse>(`/admin/users/${userId}`)).data,
  });
}
