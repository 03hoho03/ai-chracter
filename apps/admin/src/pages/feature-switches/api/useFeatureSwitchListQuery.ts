import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminFeatureSwitchListResponse } from "../model/types";
import { featureSwitchKeys } from "./keys";

/** 서버는 이 요청에서 덮어쓰기 표를 읽어 답한다(프로세스 맵이 아니다) — 다른 운영자의 저장도 다음 조회에 바로 보인다. */
export function useFeatureSwitchListQuery() {
  return useQuery<AdminFeatureSwitchListResponse, ApiError>({
    queryKey: featureSwitchKeys.list(),
    queryFn: async () => (await apiClient.get<AdminFeatureSwitchListResponse>("/admin/feature-switches")).data,
  });
}
