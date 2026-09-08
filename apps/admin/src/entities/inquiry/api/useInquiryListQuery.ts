import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { InquiryCategory } from "../model/labels";
import { inquiryKeys, type InquiryStatusFilter } from "./keys";

export type AdminInquiryListResponse = components["schemas"]["AdminInquiryListResponse"];

/** offset 페이징 — `useReportListQuery` 동형(techspec.md §6-1). status/category 미지정 시 전체 조회. */
export function useInquiryListQuery(params: { page: number; status?: InquiryStatusFilter; category?: InquiryCategory }) {
  return useQuery<AdminInquiryListResponse, ApiError>({
    queryKey: inquiryKeys.list(params),
    queryFn: async () =>
      (
        await apiClient.get<AdminInquiryListResponse>("/admin/inquiries", {
          params: { page: params.page, status: params.status, category: params.category },
        })
      ).data,
  });
}
