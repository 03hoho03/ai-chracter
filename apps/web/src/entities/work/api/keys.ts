import type { MyWorksParams } from "../model/workItem";

export const workKeys = {
  all: ["work"] as const,
  /** 내 작품 통합 목록 전부의 공통 접두 — 작품·초안·소설을 지우거나 공개 범위·편집분을 바꾼 뒤 조건과 무관하게 이
   * 접두로 무효화한다. */
  lists: () => [...workKeys.all, "list"] as const,
  /** 조건별 목록 하나. 값은 서버로 보내는 그대로라(`all` 포함) 주소에서 축이 빠진 것과 `all` 이 같은 캐시를 쓴다.
   * 검색어는 마지막 칸이다 — 검색어만 바뀐 쿼리를 가려 이전 목록을 자리표시로 남기는 판정이 그 앞까지를 견준다. */
  list: ({ type, status, q }: MyWorksParams) => [...workKeys.lists(), type, status, q ?? ""] as const,
};
