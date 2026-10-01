import type { NotificationResponse } from "./notification";

export type NotificationDestination =
  | { kind: "notice"; noticeId: string }
  | { kind: "inquiry"; inquiryId: string }
  | { kind: "comment"; contentId: string; contentType: "character" | "story"; commentId: string }
  | { kind: "none" };

/** Server types remain strings; destination.kind is the exhaustive consumer union. */
export function resolveNotificationDestination(
  notification: NotificationResponse,
): NotificationDestination {
  if (notification.type === "notice" && notification.noticeId) {
    return { kind: "notice", noticeId: notification.noticeId };
  }
  if (notification.type === "inquiry-reply" && notification.inquiryId) {
    return { kind: "inquiry", inquiryId: notification.inquiryId };
  }
  if (notification.comment) {
    return { kind: "comment", contentId: notification.comment.contentId,
      contentType: notification.comment.contentType, commentId: notification.comment.commentId };
  }
  return { kind: "none" };
}
