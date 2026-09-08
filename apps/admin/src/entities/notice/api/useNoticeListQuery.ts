import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { noticeKeys } from "./keys";

export type AdminNoticeListItem = components["schemas"]["AdminNoticeListItem"];
export type AdminNoticeListResponse = components["schemas"]["AdminNoticeListResponse"];

/** 어드민 목록은 미게시 포함, offset 페이징(`ReportsListPage` 동형, techspec.md §6-1). */
export function useNoticeListQuery(page: number) {
  return useQuery<AdminNoticeListResponse, ApiError>({
    queryKey: noticeKeys.list(page),
    queryFn: async () =>
      (await apiClient.get<AdminNoticeListResponse>("/admin/notices", { params: { page } })).data,
  });
}
