import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { profileKeys } from "./keys";

export type UserProfileResponse = components["schemas"]["UserProfileResponse"];

export function useProfileQuery(userId: string) {
  return useQuery<UserProfileResponse, ApiError>({
    queryKey: profileKeys.detail(userId),
    queryFn: async () =>
      (await apiClient.get<UserProfileResponse>(`/users/${userId}/profile`)).data,
    // 존재하지 않는 사용자(404)는 재시도해도 절대 성공하지 않으므로 즉시 에러 상태로 넘어간다.
    retry: (failureCount, error) => (error.status === 0 || error.status >= 500) && failureCount < 3,
  });
}
