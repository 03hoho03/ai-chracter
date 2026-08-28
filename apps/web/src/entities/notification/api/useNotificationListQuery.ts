import type { components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { notificationKeys } from "./keys";

export type NotificationResponse = components["schemas"]["NotificationResponse"];

const POLL_INTERVAL_MS = 30_000;

/** techspec-global-nav-profile.md §1.3 — 헤더 알림 벨 전용, 로그인 사용자에게만 마운트된다(US-032). */
export function useNotificationListQuery() {
  return useQuery({
    queryKey: notificationKeys.list(),
    queryFn: async () => (await apiClient.get<NotificationResponse[]>("/notifications")).data,
    refetchInterval: POLL_INTERVAL_MS,
  });
}
