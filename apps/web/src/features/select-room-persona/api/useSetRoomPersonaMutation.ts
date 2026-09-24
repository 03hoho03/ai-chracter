import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { chatRoomKeys, type ChatRoomState } from "@/entities/chat-room";
import { apiClient } from "@/shared/api/client";

type RoomPersonaResponse = components["schemas"]["RoomPersonaResponse"];

/** `PUT /chat-rooms/{id}/persona` — `null`이면 "선택 안 함". 응답이 방 전체가 아니라 `{personaId}`뿐이라
 * 방 상세 캐시의 그 한 칸만 응답값으로 고친다(invalidate로 메시지 전체를 다시 받지 않는다). */
export function useSetRoomPersonaMutation(roomId: string) {
  const queryClient = useQueryClient();

  return useMutation<RoomPersonaResponse, ApiError, string | null>({
    mutationFn: async (personaId) =>
      (await apiClient.put<RoomPersonaResponse>(`/chat-rooms/${roomId}/persona`, { personaId })).data,
    onSuccess: (data) => {
      queryClient.setQueryData<ChatRoomState>(chatRoomKeys.detail(roomId), (prev) =>
        prev ? { ...prev, personaId: data.personaId ?? undefined } : prev,
      );
    },
  });
}
