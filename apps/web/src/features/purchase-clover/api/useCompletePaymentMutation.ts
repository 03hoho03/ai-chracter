import type { components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { cloverKeys } from "@/entities/clover";
import { apiClient } from "@/shared/api/client";

export type CompletePaymentResponse = components["schemas"]["CompletePaymentResponse"];
export type CompletePaymentStatus = CompletePaymentResponse["status"];

/** 결제창이 끝났다고 서버에 알린다. 서버가 포트원에 다시 물어 확정하고 지급한다.
 *
 * 잔액·내역은 성공이 아니라 **끝날 때마다** 다시 읽는다 — 확인 요청이 실패해도(포트원 조회 실패 등) 웹훅이 같은 결제를
 * 맞춰 지급했을 수 있다. 잔액은 "낡았다"이지 버릴 값이 아니라 invalidate 다. */
export function useCompletePaymentMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (paymentId: string) =>
      apiClient
        .post<CompletePaymentResponse>(`/payments/${encodeURIComponent(paymentId)}/complete`)
        .then((res) => res.data),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: cloverKeys.balance() });
      void queryClient.invalidateQueries({ queryKey: cloverKeys.ledgers() });
    },
  });
}
