import { NOVEL_REFUND_NOTIFICATION_TYPE, type NotificationResponse } from "./notification";

export type NotificationDestination =
  | { kind: "notice"; noticeId: string }
  | { kind: "inquiry"; inquiryId: string }
  | { kind: "comment"; contentId: string; contentType: "character" | "story"; commentId: string }
  | { kind: "cloverHistory" }
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
  // 노벨 삭제 환급은 돌려받은 클로버를 확인할 클로버 내역(얻은 쪽)으로 간다.
  if (notification.type === NOVEL_REFUND_NOTIFICATION_TYPE) return { kind: "cloverHistory" };
  if (notification.comment) {
    return { kind: "comment", contentId: notification.comment.contentId,
      contentType: notification.comment.contentType, commentId: notification.comment.commentId };
  }
  return { kind: "none" };
}
