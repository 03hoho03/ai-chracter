import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { novelKeys } from "@/entities/novel";
import { webnovelKeys } from "@/entities/webnovel";
import { apiClient } from "@/shared/api/client";

/** `POST /novels/{id}/publication/withdraw` — 노벨 공개를 거둔다(204, 이미 거뒀어도 204). 공개 상태와 노벨 화면 캐시가
 * 낡는다. */
export function useWithdrawNovelPublicationMutation(novelId: string) {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, void>({
    mutationFn: async () => {
      await apiClient.post(`/novels/${novelId}/publication/withdraw`);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: novelKeys.publication(novelId) });
      void queryClient.invalidateQueries({ queryKey: webnovelKeys.all });
    },
  });
}
