import type { NotificationResponse } from "../api/useNotificationListQuery";

export type NotificationDestination =
  | { kind: "notice"; noticeId: string }
  | { kind: "inquiry"; inquiryId: string }
  | { kind: "none" };

/** 알림 항목의 목적지 판정 — `type`이 5종이 아니라 문자열이고 조건이 `type`과 id 필드의 조합이라
 * 유니언 exhaustiveness 축이 아니다. 공지·문의 답변만 목적지가 있고 나머지는 갈 곳이 없다(D-17). */
export function resolveNotificationDestination(
  notification: NotificationResponse,
): NotificationDestination {
  if (notification.type === "notice" && notification.noticeId) {
    return { kind: "notice", noticeId: notification.noticeId };
  }
  if (notification.type === "inquiry-reply" && notification.inquiryId) {
    return { kind: "inquiry", inquiryId: notification.inquiryId };
  }
  return { kind: "none" };
}
