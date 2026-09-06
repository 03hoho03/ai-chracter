import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { adminContentKeys } from "./keys";
import type { AdminContentDetailResponse } from "./useContentDetailQuery";

export type AdminContentActionType = components["schemas"]["ModerationActionType"];
export type ContentActionReasonCategory = components["schemas"]["ReportReasonCategory"];

type AdminContentActionPayload = {
  action: AdminContentActionType;
  reasonCategory?: ContentActionReasonCategory;
  adminComment?: string;
};

/** techspec.md §4-2 — 신고 없이 내리는 직접 조치. `restrict`/`delete`는 `reasonCategory`가
 * 필수라 누락하면 422다. `lift-restriction`은 `Notification`을 만들지 않아 `reasonCategory`가
 * 필요 없는 대신 `adminComment`가 필수다(비어 있으면 422) — `ContentActionConfirmModal`이
 * 조치별로 이 둘을 갈라 채운다. 성공 시 목록·상세 쿼리를 모두 무효화한다. */
export function useContentActionMutation(contentId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminContentDetailResponse, ApiError, AdminContentActionPayload>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminContentDetailResponse>(`/admin/contents/${contentId}/action`, payload)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminContentKeys.all }),
  });
}
