import type { components } from "@ai-character-chat/api-types";

export type CreatorPayoutApplicationStatus = components["schemas"]["AdminCreatorPayoutApplicationItem"]["status"];

export const creatorPayoutApplicationKeys = {
  all: ["creator-payout-application"] as const,
  list: (params: { page: number; status: CreatorPayoutApplicationStatus }) =>
    [...creatorPayoutApplicationKeys.all, "list", params.page, params.status] as const,
};
