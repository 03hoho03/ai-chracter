import { describe, expect, it } from "vitest";

import { commentFormSchema, EMPTY_COMMENT_VALUES } from "./schema";
import { changeCommentDraft, finishCommentDraft, newCommentDraft } from "./drafts";

describe("comment input boundaries", () => {
  it("allows emoji and a sticker alone but refuses whitespace and mentions alone", () => {
    expect(commentFormSchema.safeParse({ ...EMPTY_COMMENT_VALUES, body: "👨‍👩‍👧‍👦" }).success).toBe(true);
    expect(commentFormSchema.safeParse({ ...EMPTY_COMMENT_VALUES, stickerId: "ddona-hello" }).success).toBe(true);
    expect(commentFormSchema.safeParse({ ...EMPTY_COMMENT_VALUES, body: "  \n" }).success).toBe(false);
    expect(commentFormSchema.safeParse({
      ...EMPTY_COMMENT_VALUES, mentions: [{ id: crypto.randomUUID(), nickname: "가", profileImageUrl: null, isCreator: false }],
    }).success).toBe(false);
  });
  it("shares the visible-character 1000/1001 limit and rejects a fourth selected account", () => {
    expect(commentFormSchema.safeParse({ ...EMPTY_COMMENT_VALUES, body: "👍🏽".repeat(1000) }).success).toBe(true);
    expect(commentFormSchema.safeParse({ ...EMPTY_COMMENT_VALUES, body: "👍🏽".repeat(1001) }).success).toBe(false);
    expect(commentFormSchema.safeParse({
      ...EMPTY_COMMENT_VALUES, body: "안녕", mentions: Array.from({ length: 4 }, () => ({
        id: crypto.randomUUID(), nickname: "동명이인", profileImageUrl: null, isCreator: false,
      })),
    }).success).toBe(false);
  });
  it("retains an unchanged retry token and preserves text edited during a pending save", () => {
    const original = newCommentDraft();
    const sent = changeCommentDraft(original, { ...original.values, body: "첫 감상" });
    expect(changeCommentDraft(sent, sent.values)).toBe(sent);
    const newer = changeCommentDraft(sent, { ...sent.values, body: "전송 중 추가 감상" });
    expect(newer.requestId).not.toBe(sent.requestId);
    expect(finishCommentDraft(newer, sent.requestId)).toBe(newer);
    expect(finishCommentDraft(sent, sent.requestId).values.body).toBe("");
  });
});
