import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";

export type ContentCreateRequest = components["schemas"]["ContentCreateRequest"];
export type ContentCreateResponse = components["schemas"]["ContentCreateResponse"];

/** techspec-backend-content.md §1.2 — 빌더 진입(`/builder/$type/new`) 시 빈 초안을 만든다. */
export function useCreateContentDraftMutation() {
  return useMutation({
    mutationFn: async (payload: ContentCreateRequest) =>
      (await apiClient.post<ContentCreateResponse>("/contents", payload)).data,
  });
}
