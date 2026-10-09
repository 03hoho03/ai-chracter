import type { components } from "@ai-character-chat/api-types";

export type ReportStatusFilter = components["schemas"]["ReportStatus"];

export const reportKeys = {
  all: ["report"] as const,
  list: (params: { page: number; status?: ReportStatusFilter }) =>
    [...reportKeys.all, "list", params.page, params.status ?? "all"] as const,
  detail: (id: string) => [...reportKeys.all, "detail", id] as const,
  commentList: (params: { page: number; status?: ReportStatusFilter }) =>
    [...reportKeys.all, "comment-list", params.page, params.status ?? "all"] as const,
  commentDetail: (id: string) => [...reportKeys.all, "comment-detail", id] as const,
  chatMessageList: (params: { page: number; status?: ReportStatusFilter }) =>
    [...reportKeys.all, "chat-message-list", params.page, params.status ?? "all"] as const,
  chatMessageDetail: (id: string) => [...reportKeys.all, "chat-message-detail", id] as const,
  novelList: (params: { page: number; status?: ReportStatusFilter }) =>
    [...reportKeys.all, "novel-list", params.page, params.status ?? "all"] as const,
  novelDetail: (id: string) => [...reportKeys.all, "novel-detail", id] as const,
  novelCommentList: (params: { page: number; status?: ReportStatusFilter }) =>
    [...reportKeys.all, "novel-comment-list", params.page, params.status ?? "all"] as const,
  novelCommentDetail: (id: string) => [...reportKeys.all, "novel-comment-detail", id] as const,
};
