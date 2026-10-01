import { useMutation, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/shared/api/client";

import type { NotificationResponse } from "../model/notification";
import { notificationKeys } from "./keys";
import type { NotificationListResponse } from "./useNotificationListQuery";

export function useMarkNotificationReadMutation(viewerId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (notificationId: string) =>
      apiClient
        .patch<NotificationResponse>(`/notifications/${notificationId}/read`)
        .then((res) => res.data),
    onSuccess: (updated) => {
      queryClient.setQueryData<InfiniteData<NotificationListResponse>>(notificationKeys.list(viewerId), (previous) => previous && ({
        ...previous, pages: previous.pages.map((page) => ({
          ...page, items: page.items.map((notification) => notification.id === updated.id ? updated : notification),
        })),
      }));
      void queryClient.invalidateQueries({ queryKey: notificationKeys.viewer(viewerId) });
    },
    onError: () => toast.error("알림을 읽음 처리하지 못했어요. 잠시 후 다시 시도해주세요."),
  });
}
