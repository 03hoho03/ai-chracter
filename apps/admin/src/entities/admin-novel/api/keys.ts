import type { components } from "@ai-character-chat/api-types";

export type NovelModerationStatus = components["schemas"]["AdminNovelListItem"]["moderationStatus"];
type NovelReviewStatus = NonNullable<components["schemas"]["AdminNovelListItem"]["reviewStatus"]>;

export type AdminNovelListParams = {
  page: number;
  moderationStatus?: NovelModerationStatus;
  reviewStatus?: NovelReviewStatus;
};

export const adminNovelKeys = {
  all: ["admin-novel"] as const,
  /** 요청에 실리는 필터는 전부 키에 들어가야 한다 — 빠지면 필터만 바꾼 두 목록이 같은 캐시를 나눠 쓴다. */
  list: (params: AdminNovelListParams) =>
    [...adminNovelKeys.all, "list", params.page, params.moderationStatus ?? "all", params.reviewStatus ?? "all"] as const,
  detail: (novelId: string) => [...adminNovelKeys.all, "detail", novelId] as const,
  /** 판(`null` = 지금 판)도 요청에 실리므로 키에 넣는다 — 빠지면 한 화의 두 판이 캐시를 나눠 써 고른 판과 다른 글이 보인다. */
  chapter: (novelId: string, chapterId: string, edition: number | null) =>
    [...adminNovelKeys.all, "chapter", novelId, chapterId, edition ?? "current"] as const,
  comments: (novelId: string, page: number) => [...adminNovelKeys.all, "comments", novelId, page] as const,
  homeCurations: () => [...adminNovelKeys.all, "home-curations"] as const,
};
