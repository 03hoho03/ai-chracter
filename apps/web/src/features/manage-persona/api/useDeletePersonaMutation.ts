import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { chatRoomKeys } from "@/entities/chat-room";
import { personaKeys } from "@/entities/persona";
import { apiClient } from "@/shared/api/client";

/** 삭제하면 그 프로필을 참조하던 방의 `personaId`가 서버에서 NULL이 된다.
 * 어느 방이 참조했는지 FE는 모르므로 방 상세 캐시를 전부 invalidate한다(`removeQueries`가 아닌 이유:
 * 방 자체는 살아 있고 `personaId` 한 칸이 낡았을 뿐이다 — `apps/web/CLAUDE.md` "낡았다 vs 틀렸다"). */
export function useDeletePersonaMutation() {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, string>({
    mutationFn: async (personaId) => {
      await apiClient.delete(`/me/personas/${personaId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: personaKeys.all });
      void queryClient.invalidateQueries({ queryKey: chatRoomKeys.details() });
    },
  });
}
