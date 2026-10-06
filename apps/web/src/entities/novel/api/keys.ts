export const novelKeys = {
  all: ["novel"] as const,
  list: () => [...novelKeys.all, "list"] as const,
  detail: (novelId: string) => [...novelKeys.all, "detail", novelId] as const,
  job: (novelId: string, jobId: string) => [...novelKeys.all, "job", novelId, jobId] as const,
  /** 장 하나의 현재 본문. 소설 상세가 알려 준 현재 개정 id 를 키에 넣는다 — 상세가 새 개정을 알려 오면(다른 탭의
   * 수정·재생성) 키가 바뀌어 저절로 새로 받는다. */
  chapter: (novelId: string, chapterId: string, revisionId: string) =>
    [...novelKeys.all, "chapter", novelId, chapterId, revisionId] as const,
  /** 한 장의 모든 개정 캐시(현재 본문 캐시 전부)를 함께 가리킬 때. */
  chapterAll: (novelId: string, chapterId: string) => [...novelKeys.all, "chapter", novelId, chapterId] as const,
  revisions: (novelId: string, chapterId: string) => [...novelKeys.all, "revisions", novelId, chapterId] as const,
  revision: (novelId: string, chapterId: string, revisionId: string) =>
    [...novelKeys.all, "revision", novelId, chapterId, revisionId] as const,
};
