import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { chatRoomKeys, type ChatRoomMemory } from "@/entities/chat-room";
import { apiClient } from "@/shared/api/client";

type NoteRequest = components["schemas"]["ChatRoomMemoryNoteRequest"];
type SummaryRequest = components["schemas"]["ChatRoomMemorySummaryRequest"];

// 기억 쓰기 네 경로는 전부 조회와 같은 전체 응답을 돌려준다. 저장 성공은 invalidate가 아니라 그 응답으로
// 캐시를 바꾼다 — 폼의 기준값이 캐시에서 오므로 리페치 왕복 동안 옛 값이 보이지 않게.
function useMemoryWrite<TVariables>(roomId: string, write: (variables: TVariables) => Promise<ChatRoomMemory>) {
  const queryClient = useQueryClient();
  return useMutation<ChatRoomMemory, ApiError, TVariables>({
    mutationFn: write,
    onSuccess: (memory) => queryClient.setQueryData(chatRoomKeys.memory(roomId), memory),
  });
}

export function useSaveMemoryNoteMutation(roomId: string) {
  return useMemoryWrite(roomId, async (payload: NoteRequest) =>
    (await apiClient.put<ChatRoomMemory>(`/chat-rooms/${roomId}/memory/note`, payload)).data,
  );
}

export function useClearMemoryNoteMutation(roomId: string) {
  return useMemoryWrite(roomId, async (_: void) =>
    (await apiClient.delete<ChatRoomMemory>(`/chat-rooms/${roomId}/memory/note`)).data,
  );
}

export function useSaveMemorySummaryMutation(roomId: string) {
  return useMemoryWrite(roomId, async (payload: SummaryRequest) =>
    (await apiClient.put<ChatRoomMemory>(`/chat-rooms/${roomId}/memory/summary`, payload)).data,
  );
}

export function useRevertMemorySummaryMutation(roomId: string) {
  return useMemoryWrite(roomId, async (version: number) =>
    (await apiClient.post<ChatRoomMemory>(`/chat-rooms/${roomId}/memory/summary/revert`, { version })).data,
  );
}
