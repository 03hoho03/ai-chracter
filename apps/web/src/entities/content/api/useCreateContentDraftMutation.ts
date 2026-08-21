import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

export type ContentCreateRequest = components["schemas"]["ContentCreateRequest"];
export type ContentCreateResponse = components["schemas"]["ContentCreateResponse"];

/** techspec-backend-content.md §1.2 — 빈 초안을 만든다. 빌더 진입이 아니라 **첫 자동저장** 시점에
 * 부른다(US-007) — 진입만 하고 나간 사용자에게 빈 초안이 쌓이지 않도록. 호출부는
 * `features/build-common`의 `useDraftPersistence` 하나다. */
export function useCreateContentDraftMutation() {
  return useMutation({
    mutationFn: async (payload: ContentCreateRequest) =>
      (await apiClient.post<ContentCreateResponse>("/contents", payload)).data,
  });
}
