import type { components } from "@ai-character-chat/api-types";
import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { cloverKeys } from "./keys";

export type CloverBalanceResponse = components["schemas"]["CloverBalanceResponse"];

/** clover-techspec.md CT-12 — `staleTime`은 **30초**다.
 *
 * 🔴 `entities/session`에 얹지 않은 이유가 이것이다(CT-9): `sessionQueryOptions`는 `Infinity`라
 * 모든 변화가 **명시적 invalidate로만** 반영된다. 잔액이 바뀌는 자리는 **9곳**(차감 3표면 +
 * 환불 6지점)이라 하나를 빠뜨릴 확률이 낮지 않고, `Infinity`에서는 그 누락이 **영구 오표시**가
 * 되지만 30초에서는 **30초짜리 오표시**가 된다. 명시적 invalidate가 주 경로이고 30초는 안전망이다.
 *
 * 유한 `staleTime` 선례는 이미 있다 — `entities/image-model/api/useImageModelsQuery.ts`(30초). */
export const cloverBalanceQueryOptions = queryOptions({
  queryKey: cloverKeys.balance(),
  queryFn: async () => (await apiClient.get<CloverBalanceResponse>("/me/clover")).data,
  staleTime: 30_000,
});
