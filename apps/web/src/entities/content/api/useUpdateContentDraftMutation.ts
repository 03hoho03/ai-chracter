import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import type { ContentDraftResponse } from "./useContentDraftQuery";

export type ContentDraftPayload =
  components["schemas"]["CharacterDraftPayload"] | components["schemas"]["StoryDraftPayload"];

/** techspec-builder-common.md §1 — 자동저장/임시저장/발행 직전 저장이 공유하는 `PATCH /contents/{id}/draft`. */
export function useUpdateContentDraftMutation(id: string) {
  return useMutation({
    mutationFn: async (payload: ContentDraftPayload) =>
      (await apiClient.patch<ContentDraftResponse>(`/contents/${id}/draft`, payload)).data,
  });
}
