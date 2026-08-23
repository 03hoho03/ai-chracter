import type { ContentListSort, ContentType } from "../model/content";
// 목록 필터의 단일 소스는 `model/visibilityFilter.ts`다 — 쿼리키가 그 타입을 빌려 쓴다.
import type { VisibilityFilter } from "../model/visibilityFilter";

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
  /** US-115 — 공개범위 전환 성공 시 유형/공개여부 필터와 무관하게 그 작가의 모든 목록 쿼리를
   * 무효화하기 위한 공통 접두사(TanStack Query는 배열 접두사로 부분 매칭한다). */
  listByUser: (userId: string) => [...contentKeys.all, "list", userId] as const,
  detail: (id: string) => [...contentKeys.all, "detail", id] as const,
  draft: (id: string) => [...contentKeys.all, "draft", id] as const,
  versions: (id: string) => [...contentKeys.all, "versions", id] as const,
  browse: (params: ContentBrowseParams) => [...contentKeys.all, "browse", params] as const,
  /** 상세 조회가 조회수를 올린 뒤 유형/정렬/필터와 무관하게 홈 목록을 무효화하기 위한 공통 접두사. */
  browseAll: () => [...contentKeys.all, "browse"] as const,
  genres: () => [...contentKeys.all, "genres"] as const,
};

/** techspec-home-discovery.md §4 — 상세화면 즐겨찾기 토글 성공 시 이 키를 invalidate해 목록을 최신화한다. */
export const favoriteKeys = {
  all: ["favorites"] as const,
  list: () => [...favoriteKeys.all, "list"] as const,
};
