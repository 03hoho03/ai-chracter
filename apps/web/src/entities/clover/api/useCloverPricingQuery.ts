import type { components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { cloverKeys } from "./keys";

export type CloverProductItem = components["schemas"]["CloverProductItem"];
export type CloverPricingResponse = components["schemas"]["CloverPricingResponse"];

/** 로그인 없이 읽는 공개 가격표(충전 상품과 기본 모델 기준 단가). 웹은 가격·수량·단가 숫자의 사본을 갖지 않고
 * 이 응답만 화면에 옮긴다 — 결제를 붙이면 서버가 결제 금액을 상품 가격과 대조하므로 원본은 서버 하나여야 한다. */
export function useCloverPricingQuery() {
  return useQuery({
    queryKey: cloverKeys.pricing(),
    queryFn: async () => (await apiClient.get<CloverPricingResponse>("/clover/pricing")).data,
  });
}
