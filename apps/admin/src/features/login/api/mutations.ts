import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { useClearListSearchMemory } from "@/shared/lib/list-search-memory/listSearchMemory";

type AdminLoginRequest = components["schemas"]["AdminLoginRequest"];

export function useLoginMutation() {
  const clearListSearchMemory = useClearListSearchMemory();

  return useMutation({
    mutationFn: (payload: AdminLoginRequest) =>
      apiClient.post<void>("/admin/auth/login", payload).then((res) => res.data),
    // 로그아웃 없이 세션이 끝났다가 다른 관리자가 들어오는 경우까지 덮는다.
    onSuccess: clearListSearchMemory,
  });
}
