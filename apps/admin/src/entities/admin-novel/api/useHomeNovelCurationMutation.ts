import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminNovelKeys } from "./keys";

export type HomeNovelCurationChange =
  | { kind: "set"; position: number; novelId: string; adminComment?: string }
  | { kind: "clear"; position: number; adminComment?: string };

/** 홈 노벨 한 자리에 걸기·비우기. 걸면 그 자리의 노벨을 바꾸고, 이 노벨이 다른 자리에 있었으면 그 자리는 비워진다(한 노벨은
 * 한 자리에만). 성공·실패 모두 노벨 쿼리를 무효화한다 — 겹침 409 는 다른 운영자가 방금 바꿨다는 뜻이라 새 현황을 보여야 한다. */
export function useHomeNovelCurationMutation() {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, HomeNovelCurationChange>({
    mutationFn: async (change) => {
      const path = `/admin/home-novel-curations/${change.position}`;
      if (change.kind === "set") {
        await apiClient.put(path, { novelId: change.novelId, adminComment: change.adminComment });
        return;
      }
      await apiClient.delete(path, { data: { adminComment: change.adminComment } });
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: adminNovelKeys.all }),
  });
}
