import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";

export type ContentPublishResponse = components["schemas"]["ContentPublishResponse"];

/**
 * techspec-backend-content.md §1.2/§1.3 — `POST /contents/{id}/publish`는 요청 바디를 받지 않는다.
 * 현재 서버에 이미 저장된 초안(직전 draft PATCH가 반영해둔 최신 값)을 그대로 발행하므로, 호출부는
 * 반드시 이 뮤테이션 전에 `useUpdateContentDraftMutation`으로 최신 폼 값을 먼저 저장해야 한다.
 */
export function usePublishContentMutation(id: string) {
  return useMutation({
    mutationFn: async () => (await apiClient.post<ContentPublishResponse>(`/contents/${id}/publish`)).data,
  });
}
