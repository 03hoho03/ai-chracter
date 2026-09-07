import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminContentKeys } from "./keys";

export type AdminContentDetailResponse = components["schemas"]["AdminContentDetailResponse"];

export function useContentDetailQuery(contentId: string) {
  return useQuery<AdminContentDetailResponse, ApiError>({
    queryKey: adminContentKeys.detail(contentId),
    queryFn: async () => (await apiClient.get<AdminContentDetailResponse>(`/admin/contents/${contentId}`)).data,
  });
}
