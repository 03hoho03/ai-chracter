import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { chatRoomKeys } from "./keys";

type PlayGuideResponseDto = components["schemas"]["PlayGuideResponse"];

// techspec-chat-story.md §6, US-067 — 방 진입 시가 아니라 "더보기 > 플레이가이드" 클릭 시점에만
// 온디맨드 조회한다(enabled=false면 Sheet/Modal이 열리기 전까지 요청하지 않는다).
export function useChatRoomPlayGuideQuery(roomId: string, enabled: boolean) {
  return useQuery<PlayGuideResponseDto, ApiError>({
    queryKey: chatRoomKeys.playGuide(roomId),
    queryFn: async () =>
      (await apiClient.get<PlayGuideResponseDto>(`/chat-rooms/${roomId}/play-guide`)).data,
    enabled,
  });
}
