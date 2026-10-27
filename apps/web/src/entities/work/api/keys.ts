import type { MyWorksParams, WorkBundleKind } from "../model/workItem";

export const workKeys = {
  all: ["work"] as const,
  /** 내 작품 통합 목록 전부의 공통 접두 — 작품·초안·소설을 지우거나 공개 범위·편집분을 바꾼 뒤 조건과 무관하게 이
   * 접두로 무효화한다. */
  lists: () => [...workKeys.all, "list"] as const,
  /** 조건별 목록 하나. 값은 서버로 보내는 그대로라(`all` 포함) 주소에서 축이 빠진 것과 `all` 이 같은 캐시를 쓴다.
   * 검색어는 마지막 칸이다 — 검색어만 바뀐 쿼리를 가려 이전 목록을 자리표시로 남기는 판정이 그 앞까지를 견준다. 그래서
   * 묶음은 검색어 앞에 둔다(뒤에 두면 묶음을 바꿔도 "검색어만 바뀜"으로 읽혀 앞 묶음의 작품이 이 묶음 것처럼 남는다). */
  list: ({ type, status, bundleId, q }: MyWorksParams) =>
    [...workKeys.lists(), type, status, bundleId ?? "", q ?? ""] as const,
  /** 묶음에 든 작품 전부(커서를 끝까지 따라간 id 집합). 넣기 대화상자가 "이미 넣음"을 정확히 표시하려고 받는다 — 목록
   * 접두 아래라 넣기·빼기·지우기 뒤 목록과 함께 다시 받는다. */
  bundleMembers: (bundleId: string) => [...workKeys.lists(), "bundleMembers", bundleId] as const,
};

/** 내 작품 묶음(`/me/work-bundles`). 묶음은 나만 보는 정리라 계정마다 값이 다르다. */
export const workBundleKeys = {
  all: ["workBundle"] as const,
  /** 내 묶음 전부(이름·항목 수). 툴바 묶음 메뉴와 묶음 화면 머리가 함께 쓴다. */
  list: () => [...workBundleKeys.all, "list"] as const,
  /** 작품 하나를 기준으로 본 묶음들 — 각 묶음에 그 작품이 들었는지(`containsWork`)를 함께 받는다. */
  forWork: (kind: WorkBundleKind, workId: string) => [...workBundleKeys.all, "forWork", kind, workId] as const,
};
