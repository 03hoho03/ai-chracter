import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { promptRoutingKeys } from "@/entities/prompt-routing";
import { apiClient } from "@/shared/lib/api/client";

export type AdminPromptRouteRevisionDetailResponse = components["schemas"]["AdminPromptRouteRevisionDetailResponse"];

/** 목록은 메타만 오므로 고른 이력의 행은 이 훅으로 따로 받는다. 지금 코드가 모르는 값이 든 행은 서버가 빼고 개수만 준다. */
export function useRevisionDetailQuery(id: string) {
  return useQuery<AdminPromptRouteRevisionDetailResponse, ApiError>({
    queryKey: promptRoutingKeys.revision(id),
    queryFn: async () =>
      (await apiClient.get<AdminPromptRouteRevisionDetailResponse>(`/admin/prompt-routing/revisions/${id}`)).data,
  });
}
