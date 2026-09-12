import type { components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { contentKeys } from "./keys";

export type ContentDraftResponse =
  | components["schemas"]["CharacterDraftResponse"]
  | components["schemas"]["StoryDraftResponse"];

/** techspec-builder-character.md §1 / techspec-builder-story.md §1 — 빌더 진입 시 초안 이어쓰기용 조회.
 * `id`가 undefined면 아직 서버에 없는 초안(US-007 지연 생성)이라 조회하지 않는다 — 그 상태의 초기값은
 * `createEmptyDraft(type)`가 로컬로 만든다. */
export function useContentDraftQuery(id: string | undefined) {
  return useQuery({
    queryKey: contentKeys.draft(id ?? ""),
    queryFn: async () => (await apiClient.get<ContentDraftResponse>(`/contents/${id}/draft`)).data,
    enabled: id !== undefined,
  });
}
