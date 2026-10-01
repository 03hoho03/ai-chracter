import { describe, expect, it } from "vitest";

import { resolveCommentDraftScope, canUpdateCommentDraftScope, finishCommentDraftScope } from "./draftScope";
import { newCommentDraft, changeCommentDraft } from "./drafts";

describe("comment draft account boundaries", () => {
  it("claims guest text, sticker and reply for the first login and keeps them through 401 -> same account", () => {
    const guest = resolveCommentDraftScope(undefined, undefined, 0, newCommentDraft);
    const root = guest.drafts.root;
    if (!root) throw new Error("Expected the factory to create a root draft");
    guest.drafts.root = changeCommentDraft(root, {
      ...root.values, body: "로그인 전 감상", stickerId: "ddona-moved",
    });
    guest.activeReplyId = "reply-target";
    guest.activeEditId = "edit-target";
    const authenticated = resolveCommentDraftScope(guest, "A", 0, newCommentDraft);
    const expired = resolveCommentDraftScope(authenticated, undefined, 0, newCommentDraft);
    const restored = resolveCommentDraftScope(expired, "A", 0, newCommentDraft);
    expect(restored.drafts).toBe(guest.drafts);
    expect(restored.activeReplyId).toBe("reply-target");
    expect(restored.activeEditId).toBe("edit-target");
    expect(restored.drafts.root?.values.stickerId).toBe("ddona-moved");
    expect(restored.ownerId).toBe("A");
  });
  it("does not expose A's draft or target when B logs in, even after a 401 guest interval", () => {
    const a = resolveCommentDraftScope(undefined, "A", 0, newCommentDraft);
    const root = a.drafts.root;
    if (!root) throw new Error("Expected the factory to create a root draft");
    a.drafts.root = changeCommentDraft(root, { ...root.values, body: "A의 비공개 입력" });
    a.activeReplyId = "A-target";
    a.activeEditId = "A-edit";
    const guest = resolveCommentDraftScope(a, undefined, 0, newCommentDraft);
    const b = resolveCommentDraftScope(guest, "B", 0, newCommentDraft);
    expect(b.drafts.root?.values.body).toBe("");
    expect(b.activeReplyId).toBeUndefined();
    expect(b.activeEditId).toBeUndefined();
    expect(b.drafts.root?.requestId).not.toBe(a.drafts.root.requestId);
  });
  it("explicit logout clears text even when the same account logs back in", () => {
    const a = resolveCommentDraftScope(undefined, "A", 0, newCommentDraft);
    const root = a.drafts.root;
    if (!root) throw new Error("Expected the factory to create a root draft");
    a.drafts.root = changeCommentDraft(root, { ...root.values, body: "남기면 안 되는 입력" });
    const loggedOut = resolveCommentDraftScope(a, undefined, 1, newCommentDraft);
    const sameAccount = resolveCommentDraftScope(loggedOut, "A", 1, newCommentDraft);
    expect(sameAccount.drafts.root?.values.body).toBe("");
  });
  it("rejects A's delayed save callback after B starts typing or explicit logout occurs", () => {
    const a = resolveCommentDraftScope(undefined, "A", 0, newCommentDraft);
    const b = resolveCommentDraftScope(a, "B", 0, newCommentDraft);
    const root = b.drafts.root;
    if (!root) throw new Error("Expected the factory to create a root draft");
    b.drafts.root = changeCommentDraft(root, { ...root.values, body: "B의 새 입력" });
    expect(canUpdateCommentDraftScope(b, a, a, 0)).toBe(false);
    expect(canUpdateCommentDraftScope(a, a, a, 1)).toBe(false);
    expect(canUpdateCommentDraftScope(b, b, a, 0)).toBe(true);
    expect(b.drafts.root.values.body).toBe("B의 새 입력");
  });
  it("an earlier successful form does not close a newly selected reply or edit form", () => {
    const scope = resolveCommentDraftScope(undefined, "A", 0, newCommentDraft);
    const sent = newCommentDraft();
    scope.drafts["reply:old"] = sent;
    scope.activeReplyId = "new";
    scope.activeEditId = "editing";
    const completed = finishCommentDraftScope(scope, "reply:old", sent.requestId);
    expect(completed.activeReplyId).toBe("new");
    expect(completed.activeEditId).toBe("editing");
  });
  it("keeps the same reply form open if its draft changed while an unmounted submit was pending", () => {
    const scope = resolveCommentDraftScope(undefined, "A", 0, newCommentDraft);
    const sent = newCommentDraft();
    scope.activeReplyId = "reply";
    scope.drafts["reply:reply"] = changeCommentDraft(sent, { ...sent.values, body: "돌아와서 추가한 감상" });
    const completed = finishCommentDraftScope(scope, "reply:reply", sent.requestId);
    expect(completed.activeReplyId).toBe("reply");
    expect(completed.drafts["reply:reply"]?.values.body).toBe("돌아와서 추가한 감상");
  });
});
