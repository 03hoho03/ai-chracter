import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { promptSetKeys } from "./keys";

export type AdminPromptPreviewResponse = components["schemas"]["AdminPromptPreviewResponse"];

/** POST지만 저장된 초안을 그대로 읽어 조립할 뿐 아무것도 바꾸지 않는 조회다(LLM 호출도 없다,
 * D-10) — react-query로 캐싱해 두고 저장/게시/복원 뒤에만 무효화한다. */
export function usePreviewQuery() {
  return useQuery<AdminPromptPreviewResponse, ApiError>({
    queryKey: promptSetKeys.preview(),
    queryFn: async () =>
      (await apiClient.post<AdminPromptPreviewResponse>("/admin/prompt-sets/draft/preview")).data,
  });
}
