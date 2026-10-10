import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { personaKeys } from "@/entities/persona/@x/chat-room";
import { apiClient } from "@/shared/api/client";

import { toChatRoomState } from "./toChatRoomState";
import type { ChatRoomState } from "../model/chatRoomState";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];
type ChatRoomCreateRequestDto = components["schemas"]["ChatRoomCreateRequest"];

// "새 대화 시작"(플레이 버튼의 최초 진입 포함)의 실체. 캐릭터/스토리
// 공용(BE의 ChatRoomCreateRequest.contentType은 "character"|"story" 둘 다 허용).
export function useStartChatMutation() {
  const queryClient = useQueryClient();

  return useMutation<ChatRoomState, ApiError, ChatRoomCreateRequestDto>({
    mutationFn: async (payload) =>
      toChatRoomState((await apiClient.post<ChatRoomResponseDto>("/chat-rooms", payload)).data),
    // 프로필이 있는데 기본이 비어 있던 계정은 서버가 방을 만들며 가장 먼저 만든 프로필을 기본으로 올린다 — 목록 캐시의
    // `defaultPersonaId` 가 낡으므로 다시 읽는다. 방 화면으로 넘어가는 길을 막지 않게 기다리지 않는다.
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: personaKeys.all });
    },
  });
}
