import type { components, ApiError } from "@ai-character-chat/api-types";
import { useInfiniteQuery, type InfiniteData, type QueryKey } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { notificationKeys } from "./keys";

export type NotificationListResponse = components["schemas"]["NotificationListResponse"];

const POLL_INTERVAL_MS = 30_000;

/** 헤더 알림 벨 전용, 로그인 사용자에게만 마운트된다. */
export function useNotificationListQuery(viewerId: string) {
  return useInfiniteQuery<NotificationListResponse, ApiError, InfiniteData<NotificationListResponse, string | undefined>, QueryKey, string | undefined>({
    queryKey: notificationKeys.list(viewerId),
    queryFn: async ({ pageParam, signal }) => (await apiClient.get<NotificationListResponse>("/notifications", {
      params: { cursor: pageParam }, signal,
    })).data,
    initialPageParam: undefined,
    getNextPageParam: (page) => page.nextCursor ?? undefined,
    gcTime: 0,
    refetchInterval: POLL_INTERVAL_MS,
  });
}
