import { useMutation, useQueryClient } from "@tanstack/react-query";

import { sessionKeys } from "@/entities/session";
import { apiClient } from "@/shared/lib/api/client";

/** apps/web/CLAUDE.md — 세션 소실을 이미 마운트된 컴포넌트에 즉시 반영해야 하므로 features/logout과 동일하게 resetQueries를 쓴다. */
export function useWithdrawAccountMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => apiClient.delete<void>("/me").then((res) => res.data),
    onSuccess: () => {
      queryClient.resetQueries({ queryKey: sessionKeys.current() });
    },
  });
}
