import type { InfiniteData, QueryClient } from "@tanstack/react-query";

import { commentKeys } from "../api/keys";
import type { Comment, CommentHiddenList, CommentList, CommentLocation, CommentReplies, CommentMentionCandidates } from "./comment";

export type CommentRedaction = { commentId: string; state: "deleted" | "creator-hidden" } | { mutedUserId: string; state: "muted" };

export function redactComment(comment: Comment, action: CommentRedaction): Comment {
  const isMatched = "commentId" in action ? comment.id === action.commentId : comment.author?.id === action.mutedUserId;
  const isTargetMatched = !!comment.replyTo && ("commentId" in action
    ? comment.replyTo.id === action.commentId
    : comment.replyTo.author?.id === action.mutedUserId);
  const isThreadHidden = "commentId" in action && action.state === "creator-hidden" && comment.rootCommentId === action.commentId;
  const replyTo = isTargetMatched && comment.replyTo
    ? { ...comment.replyTo, displayState: action.state, author: null, bodyPreview: null }
    : comment.replyTo;
  if (!isMatched && !isThreadHidden) return { ...comment, replyTo, mentions: "mutedUserId" in action
    ? comment.mentions.filter((author) => author.id !== action.mutedUserId) : comment.mentions };
  return {
    ...comment, displayState: action.state,
    replyTo: replyTo ? { ...replyTo, author: null, bodyPreview: null } : null,
    author: null, body: null, sticker: null, mentions: [],
    likeCount: 0, isLiked: false, isPinned: false, canReply: false, canEdit: false,
    canDelete: action.state !== "deleted" && comment.canDelete, canLike: false, canReport: false, canPin: false,
    creatorHidden: action.state === "creator-hidden" || comment.creatorHidden,
    canCreatorHide: false,
    canCreatorRestore: action.state === "creator-hidden" && (comment.canCreatorHide || comment.canCreatorRestore),
  };
}

/** Cancel earlier reads before replacing data so a late response cannot repaint removed content. */
export async function redactCommentCaches(client: QueryClient, viewerId: string, action: CommentRedaction) {
  const scope = commentKeys.viewer(viewerId);
  await client.cancelQueries({ queryKey: scope });
  const redact = (comment: Comment) => redactComment(comment, action);
  client.setQueriesData<InfiniteData<CommentList>>({
    queryKey: scope, predicate: (query) => query.queryKey[4] === "roots",
  }, (data) => data && ({
    ...data, pages: data.pages.map((page) => ({
      ...page, pinnedComment: page.pinnedComment ? redact(page.pinnedComment) : null,
      items: page.items.map(redact).filter((comment) => comment.displayState !== "creator-hidden"),
    })),
  }));
  client.setQueriesData<InfiniteData<CommentReplies>>({
    queryKey: scope, predicate: (query) => query.queryKey[4] === "replies",
  }, (data) => data && ({ ...data, pages: data.pages.map((page) => ({ ...page, items: page.items.map(redact) })) }));
  client.setQueriesData<CommentLocation>({
    queryKey: scope, predicate: (query) => query.queryKey[4] === "location",
  }, (data) => data && ({
    ...data, root: redact(data.root), target: redact(data.target),
    replies: data.replies ? { ...data.replies, items: data.replies.items.map(redact) } : null,
  }));
  client.setQueriesData<InfiniteData<CommentHiddenList>>({
    queryKey: scope, predicate: (query) => query.queryKey[4] === "hidden",
  }, (data) => data && ({ ...data, pages: data.pages.map((page) => ({ ...page, items: page.items.map(redact) })) }));
  if ("mutedUserId" in action) {
    client.setQueriesData<InfiniteData<CommentMentionCandidates>>({
      queryKey: scope, predicate: (query) => query.queryKey[4] === "candidates",
    }, (data) => data && ({ ...data, pages: data.pages.map((page) => ({
      ...page, items: page.items.filter((author) => author.id !== action.mutedUserId),
    })) }));
  }
}
