import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import type { ChatMessageReportRequest } from "../model/schema";

type ChatMessageReportResponse = components["schemas"]["ChatMessageReportResponse"];

// 같은 메시지를 다시 신고하면 서버가 기존 신고를 같은 200 으로 돌려준다 — 화면도 첫 신고와 똑같이
// 접수 안내를 띄운다. 신고는 대화 내용을 바꾸지 않으므로 무효화할 캐시가 없다.
export function useReportChatMessageMutation(roomId: string, messageId: string) {
  return useMutation<ChatMessageReportResponse, ApiError, ChatMessageReportRequest>({
    mutationFn: async (body) => {
      const { data } = await apiClient.post<ChatMessageReportResponse>(
        `/chat-rooms/${roomId}/messages/${messageId}/report`,
        body,
      );
      return data;
    },
  });
}
