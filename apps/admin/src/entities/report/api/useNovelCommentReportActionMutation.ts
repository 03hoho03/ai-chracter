import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { reportKeys } from "./keys";
import {
  redactExpiredNovelCommentEvidence,
  type NovelCommentReportAction,
  type NovelCommentReportDetail,
} from "./novelReport";

type NovelCommentReportActionMutationOptions = {
  /** 신고 밖 화면(노벨 상세의 댓글 목록 등)의 캐시를 무효화할 자리 — 다른 entity 키라 feature 가 넘긴다. */
  onSuccess?: () => Promise<unknown> | void;
};

/** `hide`·`delete` 는 그 댓글을 숨기거나 지우고 처리완료로, `reject` 는 반려로. 댓글이 사라졌으면 409 `NOVEL_COMMENT_GONE`,
 * 이미 지운 댓글이면 409 `NOVEL_COMMENT_DELETED`(반려는 된다). */
export function useNovelCommentReportActionMutation(
  reportId: string,
  options: NovelCommentReportActionMutationOptions = {},
) {
  const queryClient = useQueryClient();
  return useMutation<NovelCommentReportDetail, ApiError, NovelCommentReportAction>({
    mutationFn: async (payload) =>
      redactExpiredNovelCommentEvidence(
        (await apiClient.post<NovelCommentReportDetail>(`/admin/novel-comment-reports/${reportId}/actions`, payload))
          .data,
      ),
    onSuccess: async (report) => {
      queryClient.setQueryData(reportKeys.novelCommentDetail(reportId), report);
      await Promise.all([queryClient.invalidateQueries({ queryKey: reportKeys.all }), options.onSuccess?.()]);
    },
  });
}
