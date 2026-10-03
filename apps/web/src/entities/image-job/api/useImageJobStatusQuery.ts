import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { getImageJobRefetchInterval, getImageJobStaleTime } from "../model/imageJobStatus";

import { imageJobKeys } from "./keys";

export type ImageJobStatusResponse = components["schemas"]["ImageJobStatusResponse"];

// 잡이 끝날 때까지 약 1.5초 간격으로 폴링하고, 완료(succeeded/failed)되거나 조회가 오류로 끝나면 멈춘다
// (useCharacterImageArchiveQuery와 동일한 enabled 패턴, jobId 미확정 구간은 호출부가 enabled=false로 넘긴다).
// 완료된 잡은 창 포커스·재연결로도 다시 묻지 않고, 오류 뒤에는 그 재조회가 회복 경로다(두 함수의 설명).
export function useImageJobStatusQuery(jobId: string, enabled: boolean) {
  return useQuery<ImageJobStatusResponse, ApiError>({
    queryKey: imageJobKeys.status(jobId),
    queryFn: async () => (await apiClient.get<ImageJobStatusResponse>(`/images/jobs/${jobId}`)).data,
    enabled,
    refetchInterval: (query) => getImageJobRefetchInterval(query.state),
    staleTime: (query) => getImageJobStaleTime(query.state.data),
  });
}
