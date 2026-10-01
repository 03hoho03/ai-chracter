import type { CommentSort } from "../model/comment";

export const commentKeys = {
  all: ["comment"] as const,
  viewer: (viewerId: string) => ["comment", viewerId] as const,
  content: (viewerId: string, contentId: string) => ["comment", viewerId, "content", contentId] as const,
  roots: (viewerId: string, contentId: string, sort: CommentSort) =>
    [...commentKeys.content(viewerId, contentId), "roots", sort] as const,
  replies: (viewerId: string, contentId: string, rootId: string, anchor?: string) =>
    [...commentKeys.content(viewerId, contentId), "replies", rootId, anchor ?? "first"] as const,
  location: (viewerId: string, contentId: string, commentId?: string) =>
    [...commentKeys.content(viewerId, contentId), "location", commentId ?? "none"] as const,
  hidden: (viewerId: string, contentId: string) => [...commentKeys.content(viewerId, contentId), "hidden"] as const,
  candidates: (viewerId: string, contentId: string, q: string) =>
    [...commentKeys.content(viewerId, contentId), "candidates", q] as const,
  stickers: ["comment-stickers"] as const,
  preferences: (viewerId: string) => [...commentKeys.viewer(viewerId), "preferences"] as const,
  mutes: (viewerId: string) => [...commentKeys.viewer(viewerId), "mutes"] as const,
};
