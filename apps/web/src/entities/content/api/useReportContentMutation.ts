import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";

export type ReportReasonCategory = components["schemas"]["ReportReasonCategory"];

export function useReportContentMutation(contentId: string) {
  return useMutation<void, ApiError, ReportReasonCategory>({
    mutationFn: async (reasonCategory) => {
      await apiClient.post(`/contents/${contentId}/report`, { reasonCategory });
    },
  });
}
