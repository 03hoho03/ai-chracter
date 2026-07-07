import type { ContentListSort, ContentType } from "../model/types";

export type VisibilityFilter = "all" | "public" | "link" | "private";

export type ContentBrowseParams = {
  type: ContentType;
  sort: ContentListSort;
  genre?: string;
  creator?: string;
  hashtag?: string;
  q?: string;
};

export const contentKeys = {
  all: ["content"] as const,
  list: (userId: string, type: ContentType, visibility?: VisibilityFilter) =>
    [...contentKeys.all, "list", userId, type, visibility ?? "all"] as const,
  detail: (id: string) => [...contentKeys.all, "detail", id] as const,
  browse: (params: ContentBrowseParams) => [...contentKeys.all, "browse", params] as const,
  genres: () => [...contentKeys.all, "genres"] as const,
};
