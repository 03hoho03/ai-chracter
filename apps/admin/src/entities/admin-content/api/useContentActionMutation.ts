import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminContentKeys } from "./keys";
import type { AdminContentDetailResponse } from "./useContentDetailQuery";

export type AdminContentActionType = components["schemas"]["ModerationActionType"];
export type ContentActionReasonCategory = components["schemas"]["ReportReasonCategory"];
type AdminContentActionRequest = components["schemas"]["AdminContentActionRequest"];

type AdminContentActionPayload = {
  action: AdminContentActionType;
  reasonCategory?: ContentActionReasonCategory;
  adminComment?: string;
  /** 이용제한·삭제가 이 작품으로 만든 노벨을 어떻게 할지. 빼면 서버는 닫고 환급한다(정책 스위치가 꺼져 있으면 환급도 없다). */
  derivativeNovels?: AdminContentActionRequest["derivativeNovels"];
};

/** 신고 없이 내리는 직접 조치. `restrict`/`delete`는 `reasonCategory`가
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
