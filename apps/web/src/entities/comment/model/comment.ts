import type { components } from "@ai-character-chat/api-types";

export type Comment = components["schemas"]["CommentResponse"];
export type CommentAuthor = components["schemas"]["CommentAuthorResponse"];
export type CommentSticker = components["schemas"]["CommentStickerResponse"];
export type CommentList = components["schemas"]["CommentListResponse"];
export type CommentReplies = components["schemas"]["CommentRepliesResponse"];
export type CommentLocation = components["schemas"]["CommentLocationResponse"];
export type CommentHiddenList = components["schemas"]["CommentHiddenListResponse"];
export type CommentPreferences = components["schemas"]["CommentNotificationPreferencesResponse"];
export type CommentMutes = components["schemas"]["CommentMutesResponse"];
export type CommentMentionCandidates = components["schemas"]["CommentMentionCandidatesResponse"];
export type CommentStickerCatalog = components["schemas"]["CommentStickerCatalogResponse"];
export type CommentReportReason = components["schemas"]["ReportReasonCategory"];
export const COMMENT_SORTS = ["latest", "popular"] as const;
export type CommentSort = (typeof COMMENT_SORTS)[number];
export type ReplyPageParam = { cursor: string; direction: "before" | "after" } | undefined;
