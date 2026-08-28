import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { appealKeys } from "./keys";

export type AppealVerdict = components["schemas"]["AppealVerdict"];
export type AdminAppealListItem = components["schemas"]["AdminAppealListItem"];

/** techspec-admin.md §2 — 처리 확정 후 이의제기 목록 쿼리를 무효화한다(US-124 AC3). */
export function useResolveAppealMutation(appealId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminAppealListItem, ApiError, AppealVerdict>({
    mutationFn: async (verdict) =>
      (await apiClient.post<AdminAppealListItem>(`/admin/appeals/${appealId}/resolve`, { verdict })).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: appealKeys.all }),
  });
}
