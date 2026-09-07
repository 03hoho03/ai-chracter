import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { noticeKeys } from "./keys";

// TODO(T-11b): codegen 후 `components["schemas"]["AdminNoticeListResponse"]`로 교체한다.
// `packages/api-types`의 codegen이 아직 안 돌아 이 스키마가 생성되지 않았다 — BE(`api/admin/notices.py`)는
// 이미 이 모양으로 응답한다.
export type AdminNoticeListItem = {
  id: string;
  title: string;
  published: boolean;
  publishedAt: string | null;
  createdAt: string;
};

export type AdminNoticeListResponse = {
  items: AdminNoticeListItem[];
  page: number;
  totalPages: number;
  totalCount: number;
};

/** 어드민 목록은 미게시 포함, offset 페이징(`ReportsListPage` 동형, techspec.md §6-1). */
export function useNoticeListQuery(page: number) {
  return useQuery<AdminNoticeListResponse, ApiError>({
    queryKey: noticeKeys.list(page),
    queryFn: async () =>
      (await apiClient.get<AdminNoticeListResponse>("/admin/notices", { params: { page } })).data,
  });
}
