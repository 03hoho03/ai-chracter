import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminNovelKeys } from "./keys";

export type AdminNovelCommentListResponse = components["schemas"]["AdminNovelCommentListResponse"];
export type AdminNovelComment = AdminNovelCommentListResponse["items"][number];

/** 노벨 하나의 댓글 전부(지운 것·숨긴 것 포함) 최신순 20개씩. */
export function useNovelCommentsQuery(novelId: string, page: number) {
  return useQuery<AdminNovelCommentListResponse, ApiError>({
    queryKey: adminNovelKeys.comments(novelId, page),
    queryFn: async () =>
      (await apiClient.get<AdminNovelCommentListResponse>(`/admin/novels/${novelId}/comments`, { params: { page } })).data,
  });
}
