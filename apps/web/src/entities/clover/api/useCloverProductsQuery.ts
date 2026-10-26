import type { components } from "@ai-character-chat/api-types";
import { queryOptions, useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { cloverKeys } from "./keys";

export type CloverProductOffer = components["schemas"]["CloverProductOffer"];
export type CloverProductsResponse = components["schemas"]["CloverProductsResponse"];
export type CloverPolicyValues = components["schemas"]["CloverPolicyValues"];

/** 로그인 없이 읽는 충전 안내(상품·결제수단·결제와 본인인증 스위치·하루 무료 대화 수·정책 숫자). 누구에게나 같은 응답이라
 * 사용자별 캐시 목록(`VIEWER_QUERY_KEYS`)에 넣지 않는다 — 로그아웃해도 그대로 쓸 수 있다. 가격·수량·정책 숫자는 이
 * 응답만 화면에 옮기고 웹에 사본을 두지 않는다. */
const cloverProductsQueryOptions = queryOptions({
  queryKey: cloverKeys.products(),
  queryFn: async () => (await apiClient.get<CloverProductsResponse>("/clover/products")).data,
});

export function useCloverProductsQuery() {
  return useQuery(cloverProductsQueryOptions);
}
