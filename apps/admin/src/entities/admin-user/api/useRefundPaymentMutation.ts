import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminUserKeys } from "./keys";

export type AdminRefundRequest = components["schemas"]["AdminRefundRequest"];
export type AdminRefundResponse = components["schemas"]["AdminRefundResponse"];

/** POST /admin/payments/{paymentId}/refund — 환불을 실행하거나, 그 결제에 진행 중 시도가 있으면 그 시도를 마무리한다.
 *
 * 멱등키가 없다: 서버에 남은 진행 중 시도 하나가 시도 단위라, 다이얼로그를 닫았다 열어도·다른 어드민이 눌러도 같은
 * 시도를 이어받는다. 그때 요청의 견적 금액·접수일·귀책은 쓰이지 않는다(사유는 서버가 여전히 비어 있으면 거부한다).
 *
 * - 200 `succeeded`: 포트원 취소 확인. 202 `requested`: 클로버는 회수했고 포트원 결과를 기다린다 — 같은 경로를
 *   다시 부르면 포트원을 재조회해 마무리한다. 두 응답은 본문 `status`로 가른다.
 * - 409 `REFUND_QUOTE_CHANGED`, 422 `REFUND_REJECTED`(회수한 클로버를 되돌렸다)·`REFUND_AMOUNT_ZERO`·
 *   `REFUND_RECEIVED_ON_INVALID`·`PAYMENT_NOT_REFUNDABLE`, 404 `PAYMENT_NOT_FOUND`는 `detail.code`로 온다.
 *
 * 🔴 `onSuccess`가 아니라 `onSettled`로 유저 쿼리를 끊는다 — 202는 회수로, 422 거절은 복원으로 잔액·원장이 이미
 * 움직였다. 성공에서만 끊으면 화면이 옛 잔액을 보인다.
 *
 * 견적만은 실패했을 때만 끊는다(409는 견적이 바뀌었다는 뜻이라 다시 읽어야 한다). 200·202 뒤에 끊으면 다이얼로그가 닫히는
 * 사이 견적을 다시 묻는데, 전액 환불된 결제는 환불할 수 없는 상태라 422가 돌아온다(진행 중 시도면 0원 견적) — 쓸모없는
 * 요청이고 닫히는 화면에 오류가 비칠 수 있다. */
export function useRefundPaymentMutation(paymentId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminRefundResponse, ApiError, AdminRefundRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminRefundResponse>(`/admin/payments/${encodeURIComponent(paymentId)}/refund`, payload))
        .data,
    onSettled: (_data, error) =>
      Promise.all([
        queryClient.invalidateQueries({
          queryKey: adminUserKeys.all,
          predicate: (query) => query.queryKey[1] !== "refund-quote",
        }),
        error ? queryClient.invalidateQueries({ queryKey: adminUserKeys.refundQuotes(paymentId) }) : undefined,
      ]),
  });
}
