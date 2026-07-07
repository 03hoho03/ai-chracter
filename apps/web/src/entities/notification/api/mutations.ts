import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { notificationKeys } from "./keys";
import type { NotificationResponse } from "./useNotificationListQuery";

export function useMarkNotificationReadMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (notificationId: string) =>
      apiClient
        .patch<NotificationResponse>(`/notifications/${notificationId}/read`)
        .then((res) => res.data),
    onSuccess: (updated) => {
      queryClient.setQueryData<NotificationResponse[]>(notificationKeys.list(), (prev) =>
        prev?.map((notification) => (notification.id === updated.id ? updated : notification)),
      );
    },
  });
}
