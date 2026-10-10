import type { components } from "@ai-character-chat/api-types";

export type CreatorPayoutStatus = components["schemas"]["AdminCreatorPayoutItem"]["status"];

export const creatorPayoutKeys = {
  all: ["creator-payout"] as const,
  list: (params: { page: number; status: CreatorPayoutStatus }) =>
    [...creatorPayoutKeys.all, "list", params.page, params.status] as const,
  detail: (payoutId: string) => [...creatorPayoutKeys.all, "detail", payoutId] as const,
  /** 회원 상세의 정산 섹션도 `all` 하위다 — 지급 처리 하나가 큐·상세·그 회원 섹션을 한 줄로 함께 끊는다. */
  user: (userId: string) => [...creatorPayoutKeys.all, "user", userId] as const,
};
