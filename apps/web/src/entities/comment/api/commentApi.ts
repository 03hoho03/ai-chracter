import type { components } from "@ai-character-chat/api-types";

import { apiClient } from "@/shared/api/client";

import type {
  Comment, CommentHiddenList, CommentList, CommentLocation, CommentMentionCandidates, CommentMutes,
  CommentPreferences, CommentReplies, CommentReportReason, CommentSort, CommentStickerCatalog, ReplyPageParam,
} from "../model/comment";

// 요청 본문과 변경 응답은 이 요청 함수들만 쓰는 전송 형태라 엔티티 타입(`model/comment.ts`)과 갈라 둔다.
export type CommentWriteRequest = components["schemas"]["CommentUpdateRequest"];
export type CommentCreateRequest = components["schemas"]["CommentCreateRequest"];
type CommentLike = components["schemas"]["CommentLikeResponse"];
type CommentPin = components["schemas"]["CommentPinResponse"];
type CommentSettings = components["schemas"]["CommentSettingsResponse"];
type CommentReport = components["schemas"]["CommentReportResponse"];

const contentPath = (contentId: string) => "/contents/" + contentId;
const commentPath = (commentId: string) => "/comments/" + commentId;

export const commentApi = {
  roots: async (contentId: string, sort: CommentSort, cursor?: string, signal?: AbortSignal) =>
    (await apiClient.get<CommentList>(contentPath(contentId) + "/comments", { params: { sort, cursor }, signal })).data,
  replies: async (contentId: string, rootId: string, page: ReplyPageParam, signal?: AbortSignal) =>
    (await apiClient.get<CommentReplies>(contentPath(contentId) + "/comments/" + rootId + "/replies",
      { params: page ?? undefined, signal })).data,
  location: async (contentId: string, commentId: string, signal?: AbortSignal) =>
    (await apiClient.get<CommentLocation>(contentPath(contentId) + "/comments/" + commentId + "/location", { signal })).data,
  hidden: async (contentId: string, cursor?: string, signal?: AbortSignal) =>
    (await apiClient.get<CommentHiddenList>(contentPath(contentId) + "/comments/hidden", { params: { cursor }, signal })).data,
  candidates: async (contentId: string, q: string, cursor?: string, signal?: AbortSignal) =>
    (await apiClient.get<CommentMentionCandidates>(contentPath(contentId) + "/comment-mention-candidates", { params: { q, cursor }, signal })).data,
  stickers: async (signal?: AbortSignal) =>
    (await apiClient.get<CommentStickerCatalog>("/comment-stickers", { signal })).data,
  create: async (contentId: string, input: CommentCreateRequest) =>
    (await apiClient.post<Comment>(contentPath(contentId) + "/comments", input)).data,
  update: async (commentId: string, input: CommentWriteRequest) =>
    (await apiClient.patch<Comment>(commentPath(commentId), input)).data,
  delete: async (commentId: string) => { await apiClient.delete(commentPath(commentId)); },
  like: async (commentId: string, isLiked: boolean) =>
    (isLiked
      ? await apiClient.put<CommentLike>(commentPath(commentId) + "/like")
      : await apiClient.delete<CommentLike>(commentPath(commentId) + "/like")).data,
  pin: async (contentId: string, commentId: string | null) =>
    (commentId
      ? await apiClient.put<CommentPin>(contentPath(contentId) + "/pinned-comment", { commentId })
      : await apiClient.delete<CommentPin>(contentPath(contentId) + "/pinned-comment")).data,
  pause: async (contentId: string, isCommentsPaused: boolean) =>
    (await apiClient.patch<CommentSettings>(contentPath(contentId) + "/comment-settings", { commentsPaused: isCommentsPaused })).data,
  hide: async (commentId: string, isHidden: boolean) => {
    if (isHidden) await apiClient.put(commentPath(commentId) + "/creator-hidden");
    else await apiClient.delete(commentPath(commentId) + "/creator-hidden");
  },
  report: async (commentId: string, reasonCategory: CommentReportReason) =>
    (await apiClient.post<CommentReport>(commentPath(commentId) + "/reports", { reasonCategory })).data,
  mutes: async (cursor?: string, signal?: AbortSignal) =>
    (await apiClient.get<CommentMutes>("/me/comment-mutes", { params: { cursor }, signal })).data,
  mute: async (userId: string, isMuted: boolean) => {
    if (isMuted) await apiClient.put("/me/comment-mutes/" + userId);
    else await apiClient.delete("/me/comment-mutes/" + userId);
  },
  preferences: async (signal?: AbortSignal) =>
    (await apiClient.get<CommentPreferences>("/me/comment-notification-preferences", { signal })).data,
  savePreferences: async (input: CommentPreferences) =>
    (await apiClient.put<CommentPreferences>("/me/comment-notification-preferences", input)).data,
};
