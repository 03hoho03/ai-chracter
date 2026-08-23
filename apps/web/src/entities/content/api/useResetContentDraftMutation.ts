import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

/** US-004 편집 취소 — 발행 후 편집한 변경분을 버리고 초안 버전을 현재 발행 버전의 내용으로 덮어쓴다.
 * 발행 버전 자체는 건드리지 않는다.
 *
 * 삭제가 아니라 덮어쓰기인 이유: `PATCH /contents/{id}/draft`가 쓰는 대상이 바로 그 초안 행이라 지우면
 * 이후 편집이 전부 404가 된다(`useDeleteContentDraftMutation`은 반대로 발행 이력이 있으면 409로 거절된다).
 *
 * 204 No Content라 mutationFn은 void를 반환하고, 캐시 무효화는 호출부가 담당한다. */
export function useResetContentDraftMutation(contentId: string) {
  return useMutation<void, ApiError, void>({
    mutationFn: async () => {
      await apiClient.post(`/contents/${contentId}/draft/reset`);
    },
  });
}
