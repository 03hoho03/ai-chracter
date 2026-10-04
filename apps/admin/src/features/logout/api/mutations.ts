import { useMutation, useQueryClient } from "@tanstack/react-query";

import { sessionKeys } from "@/entities/session";
import { apiClient } from "@/shared/lib/api/client";
import { useClearListSearchMemory } from "@/shared/lib/list-search-memory/listSearchMemory";

export function useLogoutMutation() {
  const queryClient = useQueryClient();
  const clearListSearchMemory = useClearListSearchMemory();

  return useMutation({
    mutationFn: () => apiClient.post<void>("/admin/auth/logout").then((res) => res.data),
    onSuccess: () => {
      clearListSearchMemory();
      // resetQueries synchronously clears state.data on the live Query object so any
      // mounted useSessionQuery() re-renders as logged-out immediately (see
      // apps/web/src/features/logout/api/mutations.ts for why invalidateQueries doesn't).
      void queryClient.resetQueries({ queryKey: sessionKeys.current() });
    },
  });
}
