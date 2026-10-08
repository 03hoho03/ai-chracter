import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { contentDraftSaveOptions } from "./contentDraftSaveOptions";
import type { ContentDraftResponse } from "./useContentDraftQuery";

export type ContentDraftPayload =
  components["schemas"]["CharacterDraftPayload"] | components["schemas"]["StoryDraftPayload"];

/** 자동저장/임시저장/발행 직전 저장이 공유하는 `PATCH /contents/{id}/draft`.
 * 대상 id는 훅 인자가 아니라 뮤테이션 변수다 — 지연 생성에서는 이 훅이 만들어진 렌더 시점에
 * 아직 초안이 없고, 같은 호출 안에서 방금 만든 id로 곧바로 저장해야 한다.
 *
 * `draftKey`는 저장 큐의 이름이다(`contentDraftSaveOptions`). 같은 초안의 저장은 한 줄로, 다른 초안끼리는 따로 나간다.
 * 호출부가 마운트 동안 바꾸지 않아야 한 초안의 저장이 두 줄로 갈리지 않는다. */
export function useUpdateContentDraftMutation(draftKey: string) {
  return useMutation(
    contentDraftSaveOptions(
      async ({ id, payload }: { id: string; payload: ContentDraftPayload }, signal: AbortSignal) =>
        (await apiClient.patch<ContentDraftResponse>(`/contents/${id}/draft`, payload, { signal })).data,
      draftKey,
    ),
  );
}
