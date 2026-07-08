import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";

/** techspec-builder-common.md §5.1 */
export type AppealTarget =
  | { kind: "publish-rejection"; rejectionId: string }
  | { kind: "moderation-action"; actionId: string };

type AppealResponse = components["schemas"]["AppealResponse"];

export function useSubmitAppealMutation() {
  return useMutation<AppealResponse, ApiError, { target: AppealTarget; reasonText: string }>({
    mutationFn: async ({ target, reasonText }) => {
      const { data } = await apiClient.post<AppealResponse>("/appeals", {
        targetKind: target.kind,
        targetId: target.kind === "publish-rejection" ? target.rejectionId : target.actionId,
        reasonText,
      });
      return data;
    },
  });
}
