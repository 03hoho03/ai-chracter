import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminUserKeys } from "./keys";

export type AdminRefundQuoteResponse = components["schemas"]["AdminRefundQuoteResponse"];

type RefundQuoteParams = {
  paymentId: string;
  /** 환불 신청을 받은 날(KST, YYYY-MM-DD). 비율의 7일 판정이 처리일이 아니라 이 날로 된다. */
  receivedOn: string;
  companyFault: boolean;
  enabled: boolean;
};

/** GET /admin/payments/{paymentId}/refund-quote — 아무것도 쓰지 않는 견적이다. 다이얼로그가 열려 있고 접수일이
 * 범위 안일 때만 부른다(`enabled`).
 *
 * `retry: false`: 422(접수일 범위 밖·환불할 수 없는 상태)와 404는 입력에 대한 답이라 다시 물어도 같고, 기본 재시도
 * 세 번은 그 답을 몇 초 늦게 보여 줄 뿐이다. 네트워크 실패는 호출부가 "다시 시도"로 받는다. */
export function useRefundQuoteQuery({ paymentId, receivedOn, companyFault, enabled }: RefundQuoteParams) {
  return useQuery<AdminRefundQuoteResponse, ApiError>({
    queryKey: adminUserKeys.refundQuote(paymentId, receivedOn, companyFault),
    queryFn: async () =>
      (
        await apiClient.get<AdminRefundQuoteResponse>(`/admin/payments/${encodeURIComponent(paymentId)}/refund-quote`, {
          params: { receivedOn, companyFault },
        })
      ).data,
    enabled,
    retry: false,
  });
}
