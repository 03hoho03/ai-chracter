import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { getNovelJobRefetchInterval, getNovelJobStaleTime } from "../model/novelJobPolling";

import { novelKeys } from "./keys";

export type NovelJobResponse = components["schemas"]["NovelJobResponse"];

/** `GET /novels/{novelId}/jobs/{jobId}` — 장 생성·재생성·AI 수정 작업 하나의 진행 상황. 끝날 때까지 묻고, 조회가
 * 실패해도 멈추지 않고 느린 간격으로 계속 묻는다(간격 규칙은 `getNovelJobRefetchInterval`). `jobId` 가 없으면
 * 묻지 않는다. */
export function useNovelJobQuery(novelId: string, jobId: string | undefined) {
  return useQuery<NovelJobResponse, ApiError>({
    queryKey: novelKeys.job(novelId, jobId ?? ""),
    queryFn: async () => (await apiClient.get<NovelJobResponse>(`/novels/${novelId}/jobs/${jobId ?? ""}`)).data,
    enabled: jobId !== undefined,
    refetchInterval: (query) => getNovelJobRefetchInterval(query.state),
    staleTime: (query) => getNovelJobStaleTime(query.state.data),
  });
}
