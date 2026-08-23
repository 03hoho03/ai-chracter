import { z } from "zod";

import { VISIBILITY_FILTERS, type VisibilityFilter } from "@/entities/content";

/** `/my`의 필터 칩 한 줄이 곧 하나의 축이다 — FR-18이 "초안은 `미등록`에서만 노출된다"로 못박아
 * 캐릭터/스토리(발행작 유형)와 미등록(초안)이 서로 배타적이기 때문에 단일선택 하나로 묶인다.
 * `all`은 URL에 싣지 않는다 — 파라미터의 부재가 곧 전체다. */
export const MY_WORK_TYPE_FILTERS = ["all", "character", "story", "unpublished"] as const;

export type MyWorkTypeFilter = (typeof MY_WORK_TYPE_FILTERS)[number];

/** 이번 범위의 정렬은 최신순 하나뿐이다(US-009). 옵션을 늘리려면 이 목록·`myWorksSearchSchema`뿐
 * 아니라 **`mergeMyWorks`까지** 값이 닿아야 한다 — 지금은 병합이 항상 `updatedAt` 내림차순이라
 * `sort`가 화면 표시로만 살아 있다. */
export const MY_WORKS_SORTS = ["latest"] as const;

export type MyWorksSort = (typeof MY_WORKS_SORTS)[number];

/** 필터·정렬은 전부 URL 서치 파라미터에 남아 새로고침·뒤로가기에서 보존된다(FR-19).
 * 기본값(`all` / `latest`)은 파라미터를 **비워서** 표현한다 — `?type=all&sort=latest`가 늘 붙어 있으면
 * 공유 URL이 지저분해지는 데다 "필터가 걸려 있다"는 신호 자체가 죽는다. */
export const myWorksSearchSchema = z.object({
  // 기본값 멤버(`all`)는 `.exclude()`로 뺀다 — 스키마가 `all`을 받으면 `?type=all`이 유효해져
  // "부재가 곧 기본값"이 깨진다. 목록을 손으로 다시 적으면 멤버가 늘 때 그 값이 붙은 링크가
  // `SearchParamError`로 페이지를 통째로 죽인다(`apps/web/CLAUDE.md`의 `validateSearch` 함정).
  type: z.enum(MY_WORK_TYPE_FILTERS).exclude(["all"]).optional(),
  visibility: z.enum(VISIBILITY_FILTERS).exclude(["all"]).optional(),
  sort: z.enum(MY_WORKS_SORTS).optional(),
});

export type MyWorksSearch = z.infer<typeof myWorksSearchSchema>;

/**
 * URL의 서치 파라미터를 화면·필터·건수 라벨이 함께 보는 값으로 편다. **세 축의 기본값 규칙은 여기
 * 하나뿐이다** — 한 축이라도 호출부에서 `?? 기본값`을 하면 두 번째 옵션이 붙는 순간 규칙이 두 곳이 된다.
 *
 * `미등록`(초안)에는 공개범위 자체가 없으므로 여기서 `all`로 눌러 둔다 — 칩 전환은 파라미터를 함께
 * 비우지만 손으로 만든 `?type=unpublished&visibility=private` 같은 URL이 남을 수 있고, 그때 필터는
 * 무시하는데 건수 라벨만 "비공개"라고 말하는 어긋남이 생긴다. 한 곳에서 정규화해 셋이 같은 값을 본다.
 */
export function resolveMyWorksSearch(search: MyWorksSearch): {
  type: MyWorkTypeFilter;
  visibility: VisibilityFilter;
  sort: MyWorksSort;
} {
  const type = search.type ?? "all";

  return {
    type,
    visibility: type === "unpublished" ? "all" : (search.visibility ?? "all"),
    sort: search.sort ?? "latest",
  };
}

/** Radix 단일선택 토글은 선택된 항목을 다시 누르면 빈 문자열을 흘려보내고 `SelectItem`의 value도
 * `string`이라, 화면에서 돌아오는 값에는 좁힘이 필요하다. `as` 단언 대신 술어를 쓴다. */
export function isMyWorkTypeFilter(value: string): value is MyWorkTypeFilter {
  return MY_WORK_TYPE_FILTERS.some((filter) => filter === value);
}

export function isMyWorksSort(value: string): value is MyWorksSort {
  return MY_WORKS_SORTS.some((sort) => sort === value);
}
