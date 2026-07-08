import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { toChatRoomState } from "../model/toChatRoomState";
import type { ChatRoomState } from "./types";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];
type ChatRoomCreateRequestDto = components["schemas"]["ChatRoomCreateRequest"];

// techspec-chat-common.md §3 — "새 대화 시작"(플레이 버튼의 최초 진입 포함)의 실체. BE의
// ChatRoomCreateRequest.contentType이 아직 "character" literal만 허용한다(US-057 이전) — 스토리
// 챗은 여전히 기존 스텁 라우트를 쓴다(widgets/content-detail/lib/usePlayContent.ts 참고).
export function useStartChatMutation() {
  return useMutation<ChatRoomState, ApiError, ChatRoomCreateRequestDto>({
    mutationFn: async (payload) =>
      toChatRoomState((await apiClient.post<ChatRoomResponseDto>("/chat-rooms", payload)).data),
  });
}
