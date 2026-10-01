import type { components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { notificationKeys } from "./keys";

type NotificationUnreadCountResponse = components["schemas"]["NotificationUnreadCountResponse"];

const POLL_INTERVAL_MS = 30_000;

export function useNotificationUnreadCountQuery(viewerId: string) {
  return useQuery({
    queryKey: notificationKeys.unread(viewerId),
    queryFn: async ({ signal }) => (await apiClient.get<NotificationUnreadCountResponse>("/notifications/unread-count", { signal })).data,
    gcTime: 0,
    refetchInterval: POLL_INTERVAL_MS,
  });
}
