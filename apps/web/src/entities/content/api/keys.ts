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
  draft: (id: string) => [...contentKeys.all, "draft", id] as const,
  versions: (id: string) => [...contentKeys.all, "versions", id] as const,
  browse: (params: ContentBrowseParams) => [...contentKeys.all, "browse", params] as const,
  genres: () => [...contentKeys.all, "genres"] as const,
};

/** techspec-home-discovery.md §4 — 상세화면 즐겨찾기 토글 성공 시 이 키를 invalidate해 목록을 최신화한다. */
export const favoriteKeys = {
  all: ["favorites"] as const,
  list: () => [...favoriteKeys.all, "list"] as const,
};
