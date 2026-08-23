import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

/** US-003 — 한 번도 발행된 적 없는 초안을 콘텐츠 행째로 지운다(`GET /me/drafts`가 돌려주는 것과 정확히
 * 같은 집합). 발행 이력이 있으면 서버가 409로 거절한다 — 발행이 새 초안 버전을 자동 복제하므로 발행작에도
 * 초안 행이 늘 딸려 있고, 그걸 지우면 발행작이 함께 사라지기 때문이다. 발행작의 편집 변경분만 버리는 건
 * `useResetContentDraftMutation` 쪽이다.
 *
 * 204 No Content라 mutationFn은 void를 반환하고, 캐시 무효화는 호출부가 담당한다. */
export function useDeleteContentDraftMutation(contentId: string) {
  return useMutation<void, ApiError, void>({
    mutationFn: async () => {
      await apiClient.delete(`/contents/${contentId}/draft`);
    },
  });
}
