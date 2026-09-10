import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { promptSetKeys } from "./keys";
import type { AdminPromptSetDetailResponse } from "./usePublishMutation";

/** D-16 — 목록은 메타만 오므로(`useVersionListQuery`) 라벨·섹션이 필요한 상세는 선택된
 * 버전에 한해 이 훅으로 따로 받는다. */
export function useVersionDetailQuery(id: string | undefined) {
  return useQuery<AdminPromptSetDetailResponse, ApiError>({
    queryKey: promptSetKeys.detail(id ?? ""),
    queryFn: async () => (await apiClient.get<AdminPromptSetDetailResponse>(`/admin/prompt-sets/${id}`)).data,
    enabled: id !== undefined,
  });
}
