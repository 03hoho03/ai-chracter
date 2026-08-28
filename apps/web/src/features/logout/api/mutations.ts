import { useMutation, useQueryClient } from "@tanstack/react-query";

import { sessionKeys } from "@/entities/session";
import { apiClient } from "@/shared/lib/api/client";

export function useLogoutMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => apiClient.post<void>("/auth/logout").then((res) => res.data),
    onSuccess: () => {
      // invalidateQueries only marks the query stale and refetches in the background — until that
      // refetch resolves, `data` keeps the previous (logged-in) value, so the header wouldn't switch
      // to the logged-out UI immediately. setQueryData(key, undefined) is a documented no-op (TanStack
      // Query skips the update whenever the new value resolves to undefined). removeQueries drops the
      // query from the cache but doesn't touch the Query object any still-mounted observer already
      // holds, so `useSessionQuery()` keeps rendering the stale data too. resetQueries is the one that
      // actually clears `state.data` on the live Query object and synchronously notifies observers,
      // so every mounted `useSessionQuery()` re-renders as logged-out right away.
      void queryClient.resetQueries({ queryKey: sessionKeys.current() });
    },
  });
}
