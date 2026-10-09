import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { apiClient } from "@/shared/lib/api/client";

import { reportKeys } from "./keys";
import { redactExpiredNovelCommentEvidence, type NovelCommentReportDetail } from "./novelReport";
import { useScrubExpiredEvidence } from "./useScrubExpiredEvidence";

/** 신고 시점 댓글 사본이 비활성 캐시에 남지 않게 `gcTime: 0`. */
export function useNovelCommentReportDetailQuery(reportId: string) {
  const queryKey = useMemo(() => reportKeys.novelCommentDetail(reportId), [reportId]);
  const query = useQuery<NovelCommentReportDetail, ApiError>({
    queryKey,
    queryFn: async () =>
      redactExpiredNovelCommentEvidence(
        (await apiClient.get<NovelCommentReportDetail>(`/admin/novel-comment-reports/${reportId}`)).data,
      ),
    gcTime: 0,
  });
  useScrubExpiredEvidence(
    queryKey,
    query.data?.evidence.available ? query.data.evidence.expiresAt : undefined,
    redactExpiredNovelCommentEvidence,
  );
  return query;
}
