import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { creatorPayoutKeys } from "./keys";

export type CreatorPayoutPayout = components["schemas"]["CreatorPayoutPayoutView"];
type CreatorPayoutPayoutsResponse = components["schemas"]["CreatorPayoutPayoutsResponse"];

/** 내 지급 신청(최신순). 처리 중인 지급은 한 번에 하나라 건수가 적어 서버가 페이지를 나누지 않는다. */
export function useCreatorPayoutPayoutsQuery() {
  return useQuery<CreatorPayoutPayoutsResponse, ApiError>({
    queryKey: creatorPayoutKeys.payouts(),
    queryFn: async () => (await apiClient.get<CreatorPayoutPayoutsResponse>("/me/creator-payout/payouts")).data,
  });
}
