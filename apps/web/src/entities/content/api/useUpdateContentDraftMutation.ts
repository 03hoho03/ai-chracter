import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { ContentDraftResponse } from "./useContentDraftQuery";

export type ContentDraftPayload =
  components["schemas"]["CharacterDraftPayload"] | components["schemas"]["StoryDraftPayload"];

/** techspec-builder-common.md §1 — 자동저장/임시저장/발행 직전 저장이 공유하는 `PATCH /contents/{id}/draft`.
 * 대상 id는 훅 인자가 아니라 뮤테이션 변수다 — 지연 생성(US-007)에서는 이 훅이 만들어진 렌더 시점에
 * 아직 초안이 없고, 같은 호출 안에서 방금 만든 id로 곧바로 저장해야 한다. */
export function useUpdateContentDraftMutation() {
  return useMutation({
    mutationFn: async ({ id, payload }: { id: string; payload: ContentDraftPayload }) =>
      (await apiClient.patch<ContentDraftResponse>(`/contents/${id}/draft`, payload)).data,
  });
}
