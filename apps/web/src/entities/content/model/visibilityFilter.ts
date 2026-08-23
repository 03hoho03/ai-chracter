/** 소유자에게만 보이는 공개여부 필터의 항목·타입·라벨. 프로필(`ProfileContentSection`)과 내 작품(`/my`)이
 * 같은 목록을 서로 다른 컨트롤(토글 그룹 / 드롭다운)로 그리므로 **항목만** 여기서 공유한다 —
 * 한쪽에서만 문구를 고치면 같은 작품이 화면마다 다른 단어로 불린다.
 *
 * 목록은 이 배열 하나뿐이고 **타입도 여기서 도출한다**. `as const satisfies readonly VisibilityFilter[]`로는
 * 부족하다 — `satisfies`는 원소가 멤버인지만 보고 **커버리지는 안 본다**. 그러면 멤버가 늘 때
 * `VISIBILITY_FILTER_LABEL`만 컴파일 에러를 내고, 그 에러만 고친 개발자는 이 목록과 술어가 새 값을
 * 조용히 거부한다는 걸 못 본다(드롭다운에서 영영 고를 수 없는 값이 생긴다). */
export const VISIBILITY_FILTERS = ["all", "public", "link", "private"] as const;

/** 소유자 목록 조회(`GET /users/{id}/contents?visibility=`)의 필터 값. 콘텐츠 자체의 공개범위인
 * `ContentVisibility`와 달리 "전체"(`all`)를 포함한다. */
export type VisibilityFilter = (typeof VISIBILITY_FILTERS)[number];

export const VISIBILITY_FILTER_LABEL: Record<VisibilityFilter, string> = {
  all: "전체",
  public: "공개",
  link: "링크공개",
  private: "비공개",
};

export const VISIBILITY_FILTER_OPTIONS: { value: VisibilityFilter; label: string }[] =
  VISIBILITY_FILTERS.map((value) => ({ value, label: VISIBILITY_FILTER_LABEL[value] }));

/** Radix 토글·셀렉트의 `onValueChange`는 `string`을 흘려보낸다. `as` 단언 대신 술어로 좁힌다.
 * `value in VISIBILITY_FILTER_LABEL`로 줄이지 않는 이유: `in`은 프로토타입 체인까지 보므로
 * `"toString"`·`"constructor"`가 통과한다(`Object.hasOwn`은 좁히는 대상이 키가 아니라 객체라 술어가 안 된다). */
export function isVisibilityFilter(value: string): value is VisibilityFilter {
  return VISIBILITY_FILTERS.some((filter) => filter === value);
}
