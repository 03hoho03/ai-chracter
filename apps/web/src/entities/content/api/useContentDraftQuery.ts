import type { components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { contentKeys } from "./keys";

export type ContentDraftResponse =
  | components["schemas"]["CharacterDraftResponse"]
  | components["schemas"]["StoryDraftResponse"];

/** techspec-builder-character.md §1 / techspec-builder-story.md §1 — 빌더 진입 시 초안 이어쓰기용 조회. */
export function useContentDraftQuery(id: string) {
  return useQuery({
    queryKey: contentKeys.draft(id),
    queryFn: async () => (await apiClient.get<ContentDraftResponse>(`/contents/${id}/draft`)).data,
  });
}
