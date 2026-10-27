import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import type { NovelPermission } from "../model/novelPermission";

export type ContentPublishResponse = components["schemas"]["ContentPublishResponse"];

/**
 * `POST /contents/{id}/publish`는 서버에 이미 저장된 초안(직전 draft PATCH가 반영해둔 최신 값)을 그대로 발행하므로, 호출부는
 * 반드시 이 뮤테이션 전에 `useUpdateContentDraftMutation`으로 최신 폼 값을 먼저 저장해야 한다.
 * 대상 id를 뮤테이션 변수로 받는 이유도 같다 — 지연 생성된 초안은 그 저장이 끝나야 id가 있다.
 *
 * 본문은 소설 만들기 허락 하나뿐이고 선택이다. 작가가 고른 값이 있을 때만 `{ novelPermission }` 을 싣고, 없으면 본문 없이 보낸다
 * (서버는 이 값을 선택으로 받아 오면 저장하고, 없으면 지금 값을 그대로 둔다 — 지금은 본문 없는 첫 발행을 막지 않고 로그만 남긴다).
 */
export function usePublishContentMutation() {
  return useMutation({
    mutationFn: async ({ id, novelPermission }: { id: string; novelPermission?: NovelPermission }) =>
      (
        await apiClient.post<ContentPublishResponse>(
          `/contents/${id}/publish`,
          novelPermission === undefined ? undefined : { novelPermission },
        )
      ).data,
  });
}
