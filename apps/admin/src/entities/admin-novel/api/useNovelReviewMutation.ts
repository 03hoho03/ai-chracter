import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminNovelKeys } from "./keys";

export type AdminNovelReviewRequest = components["schemas"]["AdminNovelReviewRequest"];
export type NovelReviewAction = AdminNovelReviewRequest["action"];
type AdminNovelReviewResponse = components["schemas"]["AdminNovelReviewResponse"];

/** 첫 공개 승인·반려. 반려는 사유가 필수이고(공백뿐이면 422) 그 글이 게시자 화면에 그대로 실린다. 끝나면(409 포함) 노벨
 * 쿼리 전체를 무효화한다 — 목록·상세가 심사 상태를 보이고, 승인하면 독자에게 열려 홈 노벨에 걸 수 있는지도 바뀐다. 409 는
 * 다른 운영자가 먼저 처리했거나 게시자가 신청을 취소했다는 뜻이라 새로 읽어야 한다. */
export function useNovelReviewMutation(novelId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminNovelReviewResponse, ApiError, AdminNovelReviewRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminNovelReviewResponse>(`/admin/novels/${novelId}/review`, payload)).data,
    onSettled: () => queryClient.invalidateQueries({ queryKey: adminNovelKeys.all }),
  });
}
