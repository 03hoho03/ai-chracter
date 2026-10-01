import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { ChatMessageReportList } from "./chatMessageReport";
import { reportKeys, type ReportStatusFilter } from "./keys";

export function useChatMessageReportListQuery(params: { page: number; status?: ReportStatusFilter }) {
  return useQuery<ChatMessageReportList, ApiError>({
    queryKey: reportKeys.chatMessageList(params),
    queryFn: async () => (await apiClient.get<ChatMessageReportList>("/admin/chat-message-reports", { params })).data,
  });
}
