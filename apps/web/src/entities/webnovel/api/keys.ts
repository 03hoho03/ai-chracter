/** 노벨(회원이 공개한 소설) 캐시 키. 소유자 소설(`novelKeys`, 루트 `"novel"`)과 루트를 나눈다 — 소유자 쪽 무효화
 * 술어(`novelScoped`)가 같은 소설 id 의 노벨 캐시까지 건드리지 않게.
 *
 * - `list`: 바뀌는 쓰기가 이 앱에는 없다(공개·좋아요는 다른 사람의 일이 대부분이라 들어올 때마다 새로 받는다).
 * - `detail`: 화 소장(그 화의 상태), 읽은 자리(떠날 때 다시 받는다).
 * - `chapter`: 화 소장(잠긴 화가 본문을 싣는다). */
export const webnovelKeys = {
  all: ["webnovel"] as const,
  lists: () => [...webnovelKeys.all, "list"] as const,
  list: (sort: WebnovelListSort) => [...webnovelKeys.lists(), sort] as const,
  detail: (novelId: string) => [...webnovelKeys.all, "detail", novelId] as const,
  chapter: (novelId: string, chapterId: string) => [...webnovelKeys.all, "chapter", novelId, chapterId] as const,
};

/** 목록 정렬 — 최신(공개 글이 마지막으로 바뀐 시각)과 인기(좋아요 수). */
export const WEBNOVEL_LIST_SORTS = ["latest", "popular"] as const;
export type WebnovelListSort = (typeof WEBNOVEL_LIST_SORTS)[number];
