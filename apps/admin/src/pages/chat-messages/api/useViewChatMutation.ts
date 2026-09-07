import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

export type AdminChatRoomViewRequest = components["schemas"]["AdminChatRoomViewRequest"];
export type AdminChatMessagesResponse = components["schemas"]["AdminChatMessagesResponse"];

/** 이 훅의 호출 1회 = 서버 감사 로그 1행(techspec §4-5, `apps/api/CLAUDE.md`). `useMutation`
 * 기본값이 이미 `retry: 0`이라(useQuery와 다른 점) 별도 설정 없이도 자동 재시도로 로그가
 * 중복 적재될 위험이 없다. 결과를 쿼리 캐시에 남기지 않는 이유도 같다 — 이 응답은 "그 순간의
 * 열람 결과"일 뿐 재사용할 서버 상태가 아니다. 페이지 누적(더보기와의 합산)은 호출부
 * (`ChatMessagesPage`)의 로컬 state가 맡는다. */
export function useViewChatMutation(roomId: string) {
  return useMutation<AdminChatMessagesResponse, ApiError, AdminChatRoomViewRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminChatMessagesResponse>(`/admin/chat-rooms/${roomId}/view`, payload)).data,
  });
}
