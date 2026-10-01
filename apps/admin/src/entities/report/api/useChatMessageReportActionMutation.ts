import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { ChatMessageReportAction, ChatMessageReportDetail } from "./chatMessageReport";
import { reportKeys } from "./keys";
import { redactExpiredChatMessageEvidence } from "./redactExpiredChatMessageEvidence";

type ChatMessageReportActionMutationOptions = {
  onSuccess?: (report: ChatMessageReportDetail) => Promise<void> | void;
};

/** 응답이 갱신된 상세라 그 자리에 바로 넣고, 목록(상태 칸·필터)은 `reportKeys.all`로 끊는다. */
export function useChatMessageReportActionMutation(
  reportId: string,
  options: ChatMessageReportActionMutationOptions = {},
) {
  const queryClient = useQueryClient();
  return useMutation<ChatMessageReportDetail, ApiError, ChatMessageReportAction>({
    networkMode: "always",
    mutationFn: async (payload) => redactExpiredChatMessageEvidence(
      (await apiClient.post<ChatMessageReportDetail>(`/admin/chat-message-reports/${reportId}/actions`, payload)).data,
    ),
    onSuccess: async (report) => {
      queryClient.setQueryData(reportKeys.chatMessageDetail(reportId), report);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: reportKeys.all }),
        options.onSuccess?.(report),
      ]);
    },
  });
}
