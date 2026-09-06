import type { components } from "@ai-character-chat/api-types";

export type ContentTypeFilter = components["schemas"]["ContentType"];
export type ContentVisibilityFilter = components["schemas"]["ContentVisibility"];
export type ContentModerationStatusFilter = components["schemas"]["ModerationStatus"];
export type ContentSortOption = "recent" | "views" | "chats";

export type AdminContentListParams = {
  page: number;
  type?: ContentTypeFilter;
  visibility?: ContentVisibilityFilter;
  moderationStatus?: ContentModerationStatusFilter;
  q?: string;
  sort?: ContentSortOption;
};

export const adminContentKeys = {
  all: ["admin-content"] as const,
  list: (params: AdminContentListParams) =>
    [
      ...adminContentKeys.all,
      "list",
      params.page,
      params.type ?? "all",
      params.visibility ?? "all",
      params.moderationStatus ?? "all",
      params.q ?? "",
      params.sort ?? "recent",
    ] as const,
  detail: (id: string) => [...adminContentKeys.all, "detail", id] as const,
};
