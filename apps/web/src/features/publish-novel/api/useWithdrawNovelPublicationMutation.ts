import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { novelKeys } from "@/entities/novel";
import { webnovelKeys } from "@/entities/webnovel";
import { apiClient } from "@/shared/api/client";

/** `POST /novels/{id}/publication/withdraw` — 노벨 공개를 거둔다(204, 이미 거뒀어도 204). 공개 상태와 노벨 화면 캐시가
 * 낡는다. 노벨 캐시는 낡았다고 표시만 하고 지금 다시 받지 않는다 — 거둔 화면(작품 정보의 공개 절)이 보던 노벨 작품
 * 정보(좋아요·조회 수)는 거둔 뒤 게시자에게 404 라 다시 받을 것이 없고, 노벨 화면은 들어갈 때 새로 받는다. */
export function useWithdrawNovelPublicationMutation(novelId: string) {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, void>({
    mutationFn: async () => {
      await apiClient.post(`/novels/${novelId}/publication/withdraw`);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: novelKeys.publication(novelId) });
      void queryClient.invalidateQueries({ queryKey: webnovelKeys.all, refetchType: "none" });
    },
  });
}
