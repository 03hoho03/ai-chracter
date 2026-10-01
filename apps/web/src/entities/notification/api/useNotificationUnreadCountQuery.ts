import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { notificationKeys } from "./keys";
import type { NotificationUnreadCountResponse } from "./useNotificationListQuery";

const POLL_INTERVAL_MS = 30_000;

export function useNotificationUnreadCountQuery(viewerId: string) {
  return useQuery({
    queryKey: notificationKeys.unread(viewerId),
    queryFn: async ({ signal }) => (await apiClient.get<NotificationUnreadCountResponse>("/notifications/unread-count", { signal })).data,
    gcTime: 0,
    refetchInterval: POLL_INTERVAL_MS,
  });
}
