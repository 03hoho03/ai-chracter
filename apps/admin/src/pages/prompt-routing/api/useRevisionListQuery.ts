import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { promptRoutingKeys } from "@/entities/prompt-routing";
import { apiClient } from "@/shared/lib/api/client";

export type AdminPromptRouteRevisionSummary = components["schemas"]["AdminPromptRouteRevisionSummary"];
export type AdminPromptRouteRevisionListResponse = components["schemas"]["AdminPromptRouteRevisionListResponse"];

/** 최신이 먼저다. */
export function useRevisionListQuery() {
  return useQuery<AdminPromptRouteRevisionListResponse, ApiError>({
    queryKey: promptRoutingKeys.revisions(),
    queryFn: async () =>
      (await apiClient.get<AdminPromptRouteRevisionListResponse>("/admin/prompt-routing/revisions")).data,
  });
}
