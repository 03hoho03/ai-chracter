import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { chatRoomKeys } from "./keys";
import type { ChatRoomState } from "./chat-room";

// US-079, techspec-content-versioning.md §4 — 이 확인 호출이 "봤는지 여부"의 유일한 기준점이라
// GET은 스스로 플래그를 끄지 않는다. 서버 응답을 다시 파싱하지 않고(pin과 달리 다른 필드가 바뀔
// 이유가 없다) versionAutoUpgraded만 로컬에서 false로 되돌린다.
export function useAcknowledgeVersionUpgradeMutation(roomId: string) {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, void>({
    mutationFn: async () => {
      await apiClient.post(`/chat-rooms/${roomId}/acknowledge-version-upgrade`);
    },
    onSuccess: () => {
      queryClient.setQueryData<ChatRoomState>(
        chatRoomKeys.detail(roomId),
        (prev) => prev && { ...prev, versionAutoUpgraded: false },
      );
    },
  });
}
