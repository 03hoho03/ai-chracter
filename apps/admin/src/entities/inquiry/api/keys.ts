import type { components } from "@ai-character-chat/api-types";
import type { InquiryCategory } from "../model/labels";

export type InquiryStatusFilter = components["schemas"]["InquiryStatus"];

export const inquiryKeys = {
  all: ["inquiry"] as const,
  list: (params: { page: number; status?: InquiryStatusFilter; category?: InquiryCategory }) =>
    [...inquiryKeys.all, "list", params.page, params.status ?? "all", params.category ?? "all"] as const,
  detail: (id: string) => [...inquiryKeys.all, "detail", id] as const,
};
