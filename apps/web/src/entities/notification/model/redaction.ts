import type { InfiniteData, QueryClient } from "@tanstack/react-query";

import { notificationKeys } from "../api/keys";
import type { NotificationListResponse } from "../api/useNotificationListQuery";
import type { NotificationResponse } from "./notification";

export type NotificationCommentRedaction = { commentId: string; shouldHideThread?: boolean } | { mutedUserId: string };

export function redactNotificationComment(notification: NotificationResponse, action: NotificationCommentRedaction): NotificationResponse | undefined {
  const target = notification.comment;
  if (!target) return notification;
  if ("mutedUserId" in action) {
    if (notification.type === "comment-moderated") return notification;
    return target.author?.id === action.mutedUserId ? undefined : notification;
  }
  if (target.commentId !== action.commentId && !(action.shouldHideThread && target.rootCommentId === action.commentId)) return notification;
  return { ...notification, title: "현재 상태를 확인하는 댓글 알림", comment: {
    ...target, availability: "unavailable", author: null, bodyPreview: null, stickerName: null,
  } };
}

export async function redactNotificationCaches(client: QueryClient, viewerId: string, action: NotificationCommentRedaction) {
  const scope = notificationKeys.viewer(viewerId);
  await client.cancelQueries({ queryKey: scope });
  client.setQueryData<InfiniteData<NotificationListResponse>>(notificationKeys.list(viewerId), (data) => data && ({
    ...data, pages: data.pages.map((page) => ({ ...page,
      items: page.items.map((item) => redactNotificationComment(item, action)).filter((item) => item !== undefined),
    })),
  }));
  if ("mutedUserId" in action) await client.resetQueries({ queryKey: notificationKeys.unread(viewerId) });
}
