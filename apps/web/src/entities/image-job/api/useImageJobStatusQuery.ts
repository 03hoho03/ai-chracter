import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { imageJobKeys } from "./keys";

export type ImageJobStatusResponse = components["schemas"]["ImageJobStatusResponse"];

const POLL_INTERVAL_MS = 1500;

function isTerminalStatus(status: ImageJobStatusResponse["status"]) {
  return status === "succeeded" || status === "failed";
}

// US-008 — 잡이 끝날 때까지 약 1.5초 간격으로 폴링하고, 완료(succeeded/failed)되면 멈춘다
// (useCharacterImageArchiveQuery와 동일한 enabled 패턴, jobId 미확정 구간은 호출부가 enabled=false로 넘긴다).
export function useImageJobStatusQuery(jobId: string, enabled: boolean) {
  return useQuery<ImageJobStatusResponse, ApiError>({
    queryKey: imageJobKeys.status(jobId),
    queryFn: async () => (await apiClient.get<ImageJobStatusResponse>(`/images/jobs/${jobId}`)).data,
    enabled,
    refetchInterval: (query) =>
      query.state.data && isTerminalStatus(query.state.data.status) ? false : POLL_INTERVAL_MS,
  });
}
