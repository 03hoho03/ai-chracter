import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { apiClient } from "@/shared/lib/api/client";

import { reportKeys } from "./keys";
import { redactExpiredNovelEvidence, type NovelReportDetail } from "./novelReport";
import { useScrubExpiredEvidence } from "./useScrubExpiredEvidence";

/** 신고 시점 공개본 사본이 비활성 캐시에 남지 않게 `gcTime: 0`. */
export function useNovelReportDetailQuery(reportId: string) {
  const queryKey = useMemo(() => reportKeys.novelDetail(reportId), [reportId]);
  const query = useQuery<NovelReportDetail, ApiError>({
    queryKey,
    queryFn: async () =>
      redactExpiredNovelEvidence((await apiClient.get<NovelReportDetail>(`/admin/novel-reports/${reportId}`)).data),
    gcTime: 0,
  });
  useScrubExpiredEvidence(
    queryKey,
    query.data?.evidence.available ? query.data.evidence.expiresAt : undefined,
    redactExpiredNovelEvidence,
  );
  return query;
}
