import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminUserKeys } from "./keys";

export type AdminUserPaymentListResponse = components["schemas"]["AdminUserPaymentListResponse"];
export type AdminUserPaymentItem = components["schemas"]["AdminUserPaymentItem"];

/** GET /admin/users/{id}/payments — 그 회원의 최근 주문 20건(모든 상태, 최신순). 페이지가 없다.
 * 진행 중 환불 시도가 있는 주문은 `refundPending`이 참이다(클로버는 회수했고 포트원 결과를 아직 모른다). */
export function useUserPaymentsQuery(userId: string) {
  return useQuery<AdminUserPaymentListResponse, ApiError>({
    queryKey: adminUserKeys.payments(userId),
    queryFn: async () => (await apiClient.get<AdminUserPaymentListResponse>(`/admin/users/${userId}/payments`)).data,
  });
}
