import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

export type AppealTarget =
  | { kind: "publish-rejection"; rejectionId: string }
  | { kind: "moderation-action"; actionId: string };

type AppealCreateRequest = components["schemas"]["AppealCreateRequest"];
type AppealResponse = components["schemas"]["AppealResponse"];

export function useSubmitAppealMutation() {
  return useMutation<AppealResponse, ApiError, AppealCreateRequest>({
    mutationFn: async (body) => {
      const { data } = await apiClient.post<AppealResponse>("/appeals", body);
      return data;
    },
  });
}
