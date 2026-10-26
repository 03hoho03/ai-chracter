import type { components } from "@ai-character-chat/api-types";
import { queryOptions, useQuery, type QueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { cloverKeys } from "./keys";

export type CloverProductItem = components["schemas"]["CloverProductItem"];
export type CloverPricingResponse = components["schemas"]["CloverPricingResponse"];

/** 로그인 없이 읽는 공개 가격표(충전 상품과 기본 모델 기준 단가). 웹은 가격·수량·단가 숫자의 사본을 갖지 않고
 * 이 응답만 화면에 옮긴다 — 결제를 붙이면 서버가 결제 금액을 상품 가격과 대조하므로 원본은 서버 하나여야 한다.
 * 옵션을 따로 두는 이유는 가격이 바뀌었다는 거절 뒤 훅 밖에서 같은 키·함수로 다시 받아야 해서다. */
const cloverPricingQueryOptions = queryOptions({
  queryKey: cloverKeys.pricing(),
  queryFn: async () => (await apiClient.get<CloverPricingResponse>("/clover/pricing")).data,
});

export function useCloverPricingQuery() {
  return useQuery(cloverPricingQueryOptions);
}

/** 화면이 지금 들고 있는 가격표. 요청을 보내는 순간 읽어 그 요청에 가격 버전을 싣는다 — 렌더 때 잡아 둔 값을 쓰면 확인 뒤
 * 재전송이 다시 받은 가격표가 아니라 옛 값을 싣는다. 아직 못 받았으면 undefined 다. */
export function readCloverPricing(queryClient: QueryClient): CloverPricingResponse | undefined {
  return queryClient.getQueryData(cloverPricingQueryOptions.queryKey);
}

/** 가격표를 지금 다시 받는다(캐시가 신선해도). 받은 값이 캐시에 들어가 단가를 보이는 화면도 함께 바뀐다. 실패하면 던진다. */
export function refetchCloverPricing(queryClient: QueryClient): Promise<CloverPricingResponse> {
  return queryClient.fetchQuery({ ...cloverPricingQueryOptions, staleTime: 0 });
}
