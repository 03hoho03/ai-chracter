import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminContentKeys, type ContentTypeFilter } from "./keys";

export type HomeCurationChange =
  | { kind: "set"; contentId: string; adminComment?: string }
  | { kind: "clear"; adminComment?: string };

/** 유형 한 칸의 지정·해제. 지정은 같은 유형의 기존 지정작을 바꾼다. 성공하면 작품 쿼리 전체를 무효화한다 —
 * 현황 칸과 상세 화면이 같은 키 아래에 있다. */
export function useHomeCurationMutation(contentType: ContentTypeFilter) {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, HomeCurationChange>({
    mutationFn: async (change) => {
      const path = `/admin/home-curations/${contentType}`;
      if (change.kind === "set") {
        await apiClient.put(path, { contentId: change.contentId, adminComment: change.adminComment });
        return;
      }
      await apiClient.delete(path, { data: { adminComment: change.adminComment } });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminContentKeys.all }),
  });
}
