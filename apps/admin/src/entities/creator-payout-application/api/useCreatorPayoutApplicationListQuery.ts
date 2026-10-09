import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { creatorPayoutApplicationKeys, type CreatorPayoutApplicationStatus } from "./keys";

export type AdminCreatorPayoutApplicationListResponse = components["schemas"]["AdminCreatorPayoutApplicationListResponse"];
export type AdminCreatorPayoutApplicationItem = components["schemas"]["AdminCreatorPayoutApplicationItem"];

/** 한 상태의 정산 신청, 오래된 신청부터(offset 페이지). 서버는 상태를 하나만 받는다 — "전체"가 없다.
 * 행의 자격(`eligibility`)은 신청 때가 아니라 지금 값이다. */
export function useCreatorPayoutApplicationListQuery(params: { page: number; status: CreatorPayoutApplicationStatus }) {
  return useQuery<AdminCreatorPayoutApplicationListResponse, ApiError>({
    queryKey: creatorPayoutApplicationKeys.list(params),
    queryFn: async () =>
      (
        await apiClient.get<AdminCreatorPayoutApplicationListResponse>("/admin/creator-payout/applications", {
          params: { page: params.page, status: params.status },
        })
      ).data,
  });
}
