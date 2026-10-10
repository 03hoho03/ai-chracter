import { useMutation } from "@tanstack/react-query";

import { useClearViewerSession } from "@/entities/session";
import { apiClient } from "@/shared/api/client";

export function useLogoutMutation() {
  const clearViewerSession = useClearViewerSession();

  return useMutation({
    mutationFn: () => apiClient.post<void>("/auth/logout").then((res) => res.data),
    onSuccess: () => clearViewerSession(),
  });
}
