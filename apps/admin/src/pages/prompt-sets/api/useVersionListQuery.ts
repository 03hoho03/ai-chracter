import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { promptSetKeys } from "./keys";

export type AdminPromptSetSummary = components["schemas"]["AdminPromptSetSummary"];
export type AdminPromptSetListResponse = components["schemas"]["AdminPromptSetListResponse"];

export function useVersionListQuery() {
  return useQuery<AdminPromptSetListResponse, ApiError>({
    queryKey: promptSetKeys.list(),
    queryFn: async () => (await apiClient.get<AdminPromptSetListResponse>("/admin/prompt-sets")).data,
  });
}
