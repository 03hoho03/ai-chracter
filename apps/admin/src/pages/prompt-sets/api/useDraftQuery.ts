import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminPromptDraftResponse } from "../model/schema";
import { promptSetKeys } from "./keys";

/** 저장된 초안이 없으면 서버가 활성 세트의 복제본을 그 자리에서 만들어 돌려준다(`id: null`) —
 * 부작용 없는 조회다(prompt-db-goal-prompt.md §9-1). */
export function useDraftQuery() {
  return useQuery<AdminPromptDraftResponse, ApiError>({
    queryKey: promptSetKeys.draft(),
    queryFn: async () => (await apiClient.get<AdminPromptDraftResponse>("/admin/prompt-sets/draft")).data,
  });
}
