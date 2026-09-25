import type { NotificationResponse } from "../api/useNotificationListQuery";

export type NotificationDestination =
  | { kind: "notice"; noticeId: string }
  | { kind: "inquiry"; inquiryId: string }
  | { kind: "none" };

/** 알림 항목의 목적지 판정 — 입력인 `notification.type`이 5종이 아니라 문자열이고 조건이 `type`과 id
 * 필드의 조합이라 유니언 exhaustiveness 축이 아니다. 공지·문의 답변만 목적지가 있고 나머지는 갈 곳이
 * 없다. **이건 입력(`type`)에 대한 말이다** — 출력인 반환값 `NotificationDestination.kind`는
 * 3멤버 판별유니언이라 그쪽은 exhaustiveness 축이 맞고, 소비하는 쪽(`switch`/`if`)은 `assertNever`로
 * 그걸 강제해야 한다(이 둘을 같은 말로 읽어 소비부 3곳이 무조건 fallback으로 새서 났던 지적). */
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
