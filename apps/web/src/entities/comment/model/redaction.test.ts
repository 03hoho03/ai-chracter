import { describe, expect, it } from "vitest";
import { QueryClient } from "@tanstack/react-query";

import type { Comment, CommentList } from "./comment";
import { commentKeys } from "../api/keys";
import { redactComment, redactCommentCaches } from "./redaction";

const AUTHOR = { id: "author", nickname: "현재 이름", profileImageUrl: "/private-profile", isCreator: false };
function comment(overrides: Partial<Comment> = {}): Comment {
  return {
    id: "reply-C", contentId: "work", rootCommentId: "root-A", replyToCommentId: "reply-B",
    replyTo: { id: "reply-B", author: AUTHOR, bodyPreview: "대상 원문", displayState: "normal", effectiveSpoiler: false },
    displayState: "normal", author: AUTHOR, body: "본문", sticker: null, mentions: [AUTHOR],
    isSpoiler: false, inheritedSpoiler: true, effectiveSpoiler: true, createdAt: "2026-09-30T00:00:00Z", updatedAt: null,
    isEdited: false, likeCount: 2, isLiked: true, replyCount: 0, isPinned: false, creatorHidden: false, moderatorHidden: false,
    canReply: true, canEdit: false, canDelete: false, canLike: true, canReport: true, canPin: false,
    canCreatorHide: true, canCreatorRestore: false, ...overrides,
  };
}
describe("comment cache redaction", () => {
  it("hides a whole creator-hidden thread including a normal sibling reply target and preserves inherited protection", () => {
    const hidden = redactComment(comment(), { commentId: "root-A", state: "creator-hidden" });
    expect(hidden.body).toBeNull();
    expect(hidden.author).toBeNull();
    expect(hidden.replyTo?.author).toBeNull();
    expect(hidden.replyTo?.bodyPreview).toBeNull();
    expect(hidden.mentions).toEqual([]);
    expect(hidden.inheritedSpoiler).toBe(true);
    expect(hidden.canReply).toBe(false);
  });
  it("redacts a muted target and mentions while keeping another author's reply", () => {
    const item = comment({ author: { ...AUTHOR, id: "other" } });
    const muted = redactComment(item, { mutedUserId: "author", state: "muted" });
    expect(muted.body).toBe("본문");
    expect(muted.replyTo?.author).toBeNull();
    expect(muted.mentions).toEqual([]);
    expect(muted.effectiveSpoiler).toBe(true);
  });
  it("changes only the current viewer's cached pages", async () => {
    const client = new QueryClient();
    const root = comment({ id: "root-A", rootCommentId: null, replyCount: 1 });
    const page: CommentList = { contentId: "work", contentType: "character", creatorUserId: "writer",
      canRead: true, canCreate: true, canParticipate: true, canManage: false, commentsPaused: false,
      visibleCommentCount: 2, hiddenCommentCount: null, pinnedComment: null, items: [root], nextCursor: null };
    const data = { pages: [page], pageParams: [undefined] };
    client.setQueryData(commentKeys.roots("A", "work", "latest"), data);
    client.setQueryData(commentKeys.roots("B", "work", "latest"), data);
    await redactCommentCaches(client, "A", { mutedUserId: "author", state: "muted" });
    expect(client.getQueryData<typeof data>(commentKeys.roots("A", "work", "latest"))?.pages[0]?.items[0]?.author).toBeNull();
    expect(client.getQueryData<typeof data>(commentKeys.roots("B", "work", "latest"))?.pages[0]?.items[0]?.author?.id).toBe("author");
    client.clear();
  });
});
