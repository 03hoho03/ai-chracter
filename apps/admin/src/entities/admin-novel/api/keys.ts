import type { components } from "@ai-character-chat/api-types";

export type NovelModerationStatus = components["schemas"]["AdminNovelListItem"]["moderationStatus"];

export type AdminNovelListParams = {
  page: number;
  moderationStatus?: NovelModerationStatus;
};

export const adminNovelKeys = {
  all: ["admin-novel"] as const,
  /** 요청에 실리는 필터는 전부 키에 들어가야 한다 — 빠지면 필터만 바꾼 두 목록이 같은 캐시를 나눠 쓴다. */
  list: (params: AdminNovelListParams) => [...adminNovelKeys.all, "list", params.page, params.moderationStatus ?? "all"] as const,
  detail: (novelId: string) => [...adminNovelKeys.all, "detail", novelId] as const,
  chapter: (novelId: string, chapterId: string) => [...adminNovelKeys.all, "chapter", novelId, chapterId] as const,
  comments: (novelId: string, page: number) => [...adminNovelKeys.all, "comments", novelId, page] as const,
  homeCurations: () => [...adminNovelKeys.all, "home-curations"] as const,
};
