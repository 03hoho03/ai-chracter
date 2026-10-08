import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

type CreatePaymentRequest = components["schemas"]["CreatePaymentRequest"];
export type CreatePaymentResponse = components["schemas"]["CreatePaymentResponse"];

/** 주문을 만든다. 보내는 것은 상품 키와 유료 조건 동의뿐이다 — 금액은 서버가 상품 키로 정하고, 구매자 이름·연락처는
 * 이 요청에 싣지 않는다(결제창으로만 간다). */
export function useCreatePaymentMutation() {
  return useMutation({
    mutationFn: (payload: CreatePaymentRequest) =>
      apiClient.post<CreatePaymentResponse>("/payments", payload).then((res) => res.data),
  });
}
