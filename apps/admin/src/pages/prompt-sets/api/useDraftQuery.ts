import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { PromptLane } from "../model/lane";
import type { AdminPromptDraftResponse } from "../model/schema";
import { promptSetKeys } from "./keys";

/** 저장된 초안이 없으면 서버가 그 레인의 활성 세트 복제본을 그 자리에서 만들어 돌려준다
 * (`id: null`) — 부작용 없는 조회다. */
export function useDraftQuery(lane: PromptLane) {
  return useQuery<AdminPromptDraftResponse, ApiError>({
    queryKey: promptSetKeys.draft(lane),
    queryFn: async () => (await apiClient.get<AdminPromptDraftResponse>(`/admin/prompt-sets/${lane}/draft`)).data,
  });
}
