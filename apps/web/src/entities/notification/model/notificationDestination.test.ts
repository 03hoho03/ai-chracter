import { describe, expect, it } from "vitest";

import type { NotificationResponse } from "./notification";
import { resolveNotificationDestination } from "./notificationDestination";

function notification(patch: Partial<NotificationResponse>): NotificationResponse {
  return {
    id: "n1",
    type: "moderation-action",
    contentId: null,
    actionId: null,
    noticeId: null,
    inquiryId: null,
    title: null,
    reasonCategory: null,
    adminComment: null,
    createdAt: "2026-10-09T00:00:00Z",
    read: false,
    ...patch,
  };
}

describe("resolveNotificationDestination", () => {
  it("노벨 삭제 환급은 클로버 내역으로 간다", () => {
    expect(
      resolveNotificationDestination(notification({ type: "novel-purchase-refund", novelRefund: { chapterCount: 1, cloverAmount: 30 } })),
    ).toEqual({ kind: "cloverHistory" });
  });

  it("목적지가 없는 조치 통지는 그대로 없음이다", () => {
    expect(resolveNotificationDestination(notification({}))).toEqual({ kind: "none" });
  });
});
