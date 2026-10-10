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
  /** 아래 네 접두(작가 목록·상세·초안·버전 이력)는 보는 사람에 따라 응답이 달라, 로그아웃·로그인 때 이 접두로 비운다.
   * 둘러보기·장르·홈 큐레이션은 누구에게나 같아 남긴다. */
  lists: () => [...contentKeys.all, "list"] as const,
  details: () => [...contentKeys.all, "detail"] as const,
  drafts: () => [...contentKeys.all, "draft"] as const,
  versionLists: () => [...contentKeys.all, "versions"] as const,
  list: (userId: string, type: ContentType, visibility?: VisibilityFilter) =>
    [...contentKeys.listByUser(userId), type, visibility ?? "all"] as const,
  /** 공개범위 전환 성공 시 유형/공개여부 필터와 무관하게 그 작가의 모든 목록 쿼리를
   * 무효화하기 위한 공통 접두사(TanStack Query는 배열 접두사로 부분 매칭한다). */
  listByUser: (userId: string) => [...contentKeys.lists(), userId] as const,
  detail: (id: string) => [...contentKeys.details(), id] as const,
  draft: (id: string) => [...contentKeys.drafts(), id] as const,
  versions: (id: string) => [...contentKeys.versionLists(), id] as const,
  browse: (params: ContentBrowseParams) => [...contentKeys.all, "browse", params] as const,
  /** 상세 조회가 조회수를 올린 뒤 유형/정렬/필터와 무관하게 홈 목록을 무효화하기 위한 공통 접두사. */
  browseAll: () => [...contentKeys.all, "browse"] as const,
  genres: () => [...contentKeys.all, "genres"] as const,
  /** `browse` 아래에 두지 않는다 — 상세 열람 뒤 `browseAll()` 무효화가 조회수를 다시 받으려는 것인데 이 응답엔
   * 조회수가 없어 같이 다시 받을 이유가 없다. */
  homeCuration: (type: ContentType) => [...contentKeys.all, "home-curation", type] as const,
};

/** 상세화면 즐겨찾기 토글 성공 시 이 키를 invalidate해 목록을 최신화한다.
 * `type`이 쿼리키에 들어간다 — 없으면 캐릭터/스토리 두 타입이 같은 캐시
 * 엔트리를 공유해 한쪽 목록이 반대 타입 데이터를 보여줄 수 있다. */
export const favoriteKeys = {
  all: ["favorites"] as const,
  list: (type: ContentType) => [...favoriteKeys.all, "list", type] as const,
};
