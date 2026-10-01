import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { apiClient } from "@/shared/lib/api/client";

import type { CommentReportDetail } from "./commentReport";
import { reportKeys } from "./keys";
import { redactExpiredEvidence } from "./redactExpiredEvidence";

export function useCommentReportDetailQuery(reportId: string) {
  const queryClient = useQueryClient();
  const query = useQuery<CommentReportDetail, ApiError>({
    queryKey: reportKeys.commentDetail(reportId),
    queryFn: async () => redactExpiredEvidence(
      (await apiClient.get<CommentReportDetail>(`/admin/comment-reports/${reportId}`)).data,
    ),
    gcTime: 0,
  });
  const expiresAt = query.data?.evidence.available ? query.data.evidence.expiresAt : undefined;

  // 외부 시계와 동기화한다. 만료된 원문은 화면뿐 아니라 활성 쿼리 캐시에서도 제거한다.
  useEffect(() => {
    if (!expiresAt) return;
    const scrub = () => {
      queryClient.setQueryData<CommentReportDetail>(reportKeys.commentDetail(reportId), (report) =>
        report ? redactExpiredEvidence(report) : report,
      );
    };
    let timer: number;
    const schedule = () => {
      const remaining = Date.parse(expiresAt) - Date.now();
      if (remaining <= 0) { scrub(); return; }
      timer = window.setTimeout(schedule, Math.min(remaining, 2_147_483_647));
    };
    schedule();
    document.addEventListener("visibilitychange", scrub);
    window.addEventListener("focus", scrub);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", scrub);
      window.removeEventListener("focus", scrub);
    };
  }, [expiresAt, queryClient, reportId]);

  return query;
}
