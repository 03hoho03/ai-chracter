import { useMutation, useQueryClient } from "@tanstack/react-query";

import { sessionKeys } from "@/entities/session";
import { apiClient } from "@/shared/lib/api/client";

export function useLogoutMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => apiClient.post<void>("/admin/auth/logout").then((res) => res.data),
    onSuccess: () => {
      // resetQueries synchronously clears state.data on the live Query object so any
      // mounted useSessionQuery() re-renders as logged-out immediately (see
      // apps/web/src/features/logout/api/mutations.ts for why invalidateQueries doesn't).
      queryClient.resetQueries({ queryKey: sessionKeys.current() });
    },
  });
}
