import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import type { ContentVisibility } from "../model/types";

/** techspec-content-versioning.md §1, US-115(FR-67) — 발행 콘텐츠는 완전 삭제 없이 비공개 전환만
 * 허용된다. 204 No Content라 mutationFn은 void를 반환하고, 캐시 무효화는 호출부가 담당한다. */
export function useUpdateContentVisibilityMutation(contentId: string) {
  return useMutation<void, ApiError, ContentVisibility>({
    mutationFn: async (visibility) => {
      await apiClient.patch(`/contents/${contentId}/visibility`, { visibility });
    },
  });
}
