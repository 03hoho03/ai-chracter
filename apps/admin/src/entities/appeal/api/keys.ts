import type { components } from "@ai-character-chat/api-types";

export type AppealStatusFilter = components["schemas"]["AppealStatus"];

export const appealKeys = {
  all: ["appeal"] as const,
  list: (params: { page: number; status?: AppealStatusFilter }) =>
    [...appealKeys.all, "list", params.page, params.status ?? "all"] as const,
};
