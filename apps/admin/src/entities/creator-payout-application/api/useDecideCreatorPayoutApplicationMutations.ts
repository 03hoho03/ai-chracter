import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { creatorPayoutApplicationKeys } from "./keys";

export type AdminCreatorPayoutApproveResponse = components["schemas"]["AdminCreatorPayoutApproveResponse"];

const applicationPath = (applicationId: string, action: "approve" | "reject" | "revoke") =>
  `/admin/creator-payout/applications/${encodeURIComponent(applicationId)}/${action}`;

/**
 * 성공이 아니라 끝날 때마다 목록을 다시 읽는다 — 409(이미 처리됨·자격 없음)·404 는 화면의 행이 낡았다는 뜻이라
 * 실패에서도 새 상태·자격을 보여야 한다.
 */
function useInvalidateApplications() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: creatorPayoutApplicationKeys.all });
}

/** 승인. 처음 승인이면 서버가 지난 소급 기간을 같은 요청에서 확정하고 그 금액(원)을 돌려준다. 다시 승인이면 `null`.
 * 메모(`reasonText`)는 감사 기록에만 남는다. */
export function useApproveCreatorPayoutApplicationMutation(applicationId: string) {
  const invalidate = useInvalidateApplications();
  return useMutation<AdminCreatorPayoutApproveResponse, ApiError, { reasonText: string }>({
    mutationFn: async (body) =>
      (await apiClient.post<AdminCreatorPayoutApproveResponse>(applicationPath(applicationId, "approve"), body)).data,
    onSettled: invalidate,
  });
}

/** 거절. 사유는 신청자 화면에 그대로 보인다. */
export function useRejectCreatorPayoutApplicationMutation(applicationId: string) {
  const invalidate = useInvalidateApplications();
  return useMutation<void, ApiError, { reasonText: string }>({
    mutationFn: async (body) => {
      await apiClient.post(applicationPath(applicationId, "reject"), body);
    },
    onSettled: invalidate,
  });
}

/** 승인 취소. 그 시각부터 적립이 멈추고 확정된 적립은 남는다. 사유는 거절 사유처럼 신청자 정산 화면에 보인다. */
export function useRevokeCreatorPayoutApplicationMutation(applicationId: string) {
  const invalidate = useInvalidateApplications();
  return useMutation<void, ApiError, { reasonText: string }>({
    mutationFn: async (body) => {
      await apiClient.post(applicationPath(applicationId, "revoke"), body);
    },
    onSettled: invalidate,
  });
}
