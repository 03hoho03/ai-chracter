import { describe, expect, it } from "vitest";
import { QueryClient } from "@tanstack/react-query";

import { notificationKeys } from "../api/keys";
import type { NotificationListResponse, NotificationResponse } from "../api/useNotificationListQuery";
import { redactNotificationComment, redactNotificationCaches } from "./redaction";

function notification(type = "comment-reply"): NotificationResponse {
  return { id: "event", type, read: false, contentId: "work", actionId: null, noticeId: null, inquiryId: null,
    title: "댓글 알림", reasonCategory: null, adminComment: null, createdAt: "2026-09-30T00:00:00Z",
    comment: { contentId: "work", contentType: "story", commentId: "reply", rootCommentId: "root", availability: "available",
      isSpoiler: false, author: { id: "author", nickname: "이름", profileImageUrl: "/profile", isCreator: false },
      bodyPreview: "알림 원문", stickerName: "감동" } };
}
describe("current comment notification protection", () => {
  it("immediately removes cached body, sticker and identity for a hidden root's reply event", () => {
    const hidden = redactNotificationComment(notification(), { commentId: "root", shouldHideThread: true });
    expect(hidden?.comment?.bodyPreview).toBeNull();
    expect(hidden?.comment?.stickerName).toBeNull();
    expect(hidden?.comment?.author).toBeNull();
    expect(hidden?.comment?.availability).toBe("unavailable");
  });
  it("mutes conversation events while preserving moderation and the previous notice destination", () => {
    expect(redactNotificationComment(notification(), { mutedUserId: "author" })).toBeUndefined();
    const moderation = notification("comment-moderated");
    expect(redactNotificationComment(moderation, { mutedUserId: "author" })).toBe(moderation);
    const notice = { ...notification("notice"), comment: null, noticeId: "notice" };
    expect(redactNotificationComment(notice, { mutedUserId: "author" })).toBe(notice);
  });
  it("removes a moderation event's old preview when the author changes spoiler visibility or deletes the comment", () => {
    const moderation = notification("comment-moderated");
    const scrubbed = redactNotificationComment(moderation, { commentId: "reply" });
    expect(scrubbed?.comment?.bodyPreview).toBeNull();
    expect(scrubbed?.comment?.stickerName).toBeNull();
    expect(scrubbed?.comment?.author).toBeNull();
    expect(scrubbed?.type).toBe("comment-moderated");
  });
  it("filters muted events from only the current viewer's cache without dropping moderation or pagination", async () => {
    const client = new QueryClient();
    const items = [notification(), { ...notification("comment-moderated"), id: "moderation" },
      { ...notification("notice"), id: "notice", comment: null, noticeId: "notice" }];
    const page: NotificationListResponse = { items, nextCursor: "next", unreadCount: 3 };
    const data = { pages: [page], pageParams: [undefined] };
    client.setQueryData(notificationKeys.list("A"), data);
    client.setQueryData(notificationKeys.list("B"), data);
    client.setQueryData(notificationKeys.unread("A"), { unreadCount: 3 });
    client.setQueryData(notificationKeys.unread("B"), { unreadCount: 3 });

    await redactNotificationCaches(client, "A", { mutedUserId: "author" });

    const current = client.getQueryData<typeof data>(notificationKeys.list("A"));
    expect(current?.pages[0]?.items.map((item) => item.id)).toEqual(["moderation", "notice"]);
    expect(current?.pages[0]?.nextCursor).toBe("next");
    expect(current?.pageParams).toEqual([undefined]);
    expect(client.getQueryData(notificationKeys.list("B"))).toEqual(data);
    expect(client.getQueryData(notificationKeys.unread("A"))).toBeUndefined();
    expect(client.getQueryData(notificationKeys.unread("B"))).toEqual({ unreadCount: 3 });
    client.clear();
  });
});
