import type { components } from "@ai-character-chat/api-types";

export type ReportStatusFilter = components["schemas"]["ReportStatus"];

export const reportKeys = {
  all: ["report"] as const,
  list: (params: { page: number; status?: ReportStatusFilter }) =>
    [...reportKeys.all, "list", params.page, params.status ?? "all"] as const,
  detail: (id: string) => [...reportKeys.all, "detail", id] as const,
};
