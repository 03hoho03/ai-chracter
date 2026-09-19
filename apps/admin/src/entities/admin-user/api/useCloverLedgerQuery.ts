import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminUserKeys } from "./keys";

export type AdminCloverLedgerListResponse = components["schemas"]["AdminCloverLedgerListResponse"];
export type AdminCloverLedgerItem = components["schemas"]["AdminCloverLedgerItem"];

/** GET /admin/users/{id}/clover-ledger — clover-techspec.md §4-5. offset 페이지네이션(20건)이고
 * BE가 `(created_at desc, id)`로 동률까지 안정 정렬한다.
 *
 * 🔴 호출부는 **첫 페이지만** 쓴다(사용자 결정 — 전용 목록 페이지는 만들지 않는다). 라우트가
 * `page`를 받는 것은 나중에 필요해질 때 화면만 더하면 되게 둔 것이고, 지금 페이지 이동 UI를
 * 만들면 쓰이지 않는 코드가 된다. `totalCount`는 "최근 20건 / 전체 N건"을 말하는 데 쓴다. */
export function useCloverLedgerQuery(userId: string, page = 1) {
  return useQuery<AdminCloverLedgerListResponse, ApiError>({
    queryKey: adminUserKeys.cloverLedger(userId, page),
    queryFn: async () =>
      (
        await apiClient.get<AdminCloverLedgerListResponse>(`/admin/users/${userId}/clover-ledger`, {
          params: { page },
        })
      ).data,
  });
}
