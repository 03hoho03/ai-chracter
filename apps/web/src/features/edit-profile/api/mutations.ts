import type { components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { profileKeys } from "../../../entities/profile";
import { sessionKeys } from "../../../entities/session";
import { apiClient } from "../../../shared/lib/api/client";

type UpdateProfileRequest = components["schemas"]["UpdateProfileRequest"];
type UserProfileResponse = components["schemas"]["UserProfileResponse"];

export function useUpdateProfileMutation(userId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: UpdateProfileRequest) =>
      apiClient.patch<UserProfileResponse>("/me/profile", payload).then((res) => res.data),
    onSuccess: (data) => {
      queryClient.setQueryData(profileKeys.detail(userId), data);
      // MeResponse(GET /me)도 nickname/bio/profileImageAssetId를 갖고 있어 헤더 등 이미 마운트된
      // 화면이 이 값을 들고 있을 수 있다 — staleTime: Infinity라 무효화하지 않으면 갱신되지 않는다.
      void queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
    },
  });
}
