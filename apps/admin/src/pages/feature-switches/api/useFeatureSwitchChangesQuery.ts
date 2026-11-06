import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminFeatureSwitchChangeListResponse } from "../model/types";
import { featureSwitchKeys } from "./keys";

/** 최신 먼저 20건씩. `switchName` 이 없으면 모든 스위치의 이력이다. */
export function useFeatureSwitchChangesQuery(params: { page: number; switchName?: string }) {
  return useQuery<AdminFeatureSwitchChangeListResponse, ApiError>({
    queryKey: featureSwitchKeys.changes(params),
    queryFn: async () =>
      (
        await apiClient.get<AdminFeatureSwitchChangeListResponse>("/admin/feature-switches/changes", {
          params: { page: params.page, switch: params.switchName },
        })
      ).data,
  });
}
