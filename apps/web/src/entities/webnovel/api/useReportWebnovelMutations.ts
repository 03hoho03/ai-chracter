import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

type ReportReasonCategory = components["schemas"]["ReportReasonCategory"];

/** `POST /webnovels/{novelId}/reports` — 노벨(`chapterId` 없음)이나 그 공개 화 하나를 신고한다. 같은 대상을 다시
 * 신고하면 서버가 처음 신고를 그대로 돌려준다(사유를 바꾸지 않는다). 캐시는 바뀌지 않는다. */
export function useReportWebnovelMutation(novelId: string) {
  return useMutation<void, ApiError, { reasonCategory: ReportReasonCategory; chapterId?: string }>({
    mutationFn: async ({ reasonCategory, chapterId }) => {
      await apiClient.post(`/webnovels/${novelId}/reports`, { reasonCategory, chapterId: chapterId ?? null });
    },
  });
}

/** `POST /webnovels/{novelId}/comments/{commentId}/reports` — 남의 화 댓글을 신고한다. */
export function useReportWebnovelCommentMutation(novelId: string) {
  return useMutation<void, ApiError, { commentId: string; reasonCategory: ReportReasonCategory }>({
    mutationFn: async ({ commentId, reasonCategory }) => {
      await apiClient.post(`/webnovels/${novelId}/comments/${commentId}/reports`, { reasonCategory });
    },
  });
}
