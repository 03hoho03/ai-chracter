import type { ContentType } from "../model/types";

export type VisibilityFilter = "all" | "public" | "link" | "private";

export const contentKeys = {
  all: ["content"] as const,
  list: (userId: string, type: ContentType, visibility?: VisibilityFilter) =>
    [...contentKeys.all, "list", userId, type, visibility ?? "all"] as const,
  detail: (id: string) => [...contentKeys.all, "detail", id] as const,
};
