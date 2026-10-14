export const draftKeys = {
  all: ["draft"] as const,
  /** 초안 목록 쿼리 전부의 공통 접두사 — 초안을 만들거나 지운 뒤 검색어와 무관하게 이 접두로 무효화한다. */
  list: () => [...draftKeys.all, "list"] as const,
  /** 검색어별 목록 하나. 검색어가 없으면 그 칸은 빈 문자열이다. */
  listByQuery: (q?: string) => [...draftKeys.list(), q ?? ""] as const,
};
