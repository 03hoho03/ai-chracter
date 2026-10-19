import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminNovelKeys } from "./keys";

export type AdminNovelSalesRequest = components["schemas"]["AdminNovelSalesRequest"];
export type NovelSalesAction = AdminNovelSalesRequest["action"];
type AdminNovelSalesResponse = components["schemas"]["AdminNovelSalesResponse"];

/** 노벨 판매 중단·재개. 사유는 필수(공백뿐이면 422)이고, 이미 그 상태면 409, 정책 스위치가 꺼져 있으면 409
 * `NOVEL_SALES_STOP_DISABLED` 다(재개도 막힌다). 끝나면(409 포함) 노벨 쿼리 전체를 무효화한다 — 목록·상세·홈 노벨 현황이
 * 모두 독자에게 보이는지를 보이고, 409 는 다른 운영자가 먼저 바꿨다는 뜻이다. */
export function useNovelSalesMutation(novelId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminNovelSalesResponse, ApiError, AdminNovelSalesRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminNovelSalesResponse>(`/admin/novels/${novelId}/sales`, payload)).data,
    onSettled: () => queryClient.invalidateQueries({ queryKey: adminNovelKeys.all }),
  });
}
