import type { VisibilityFilter } from "@/entities/content";

import type { StudioSearch } from "./studioSearch";

/** 옛 내 작품 화면(`/my`)이 주소에 싣던 조건. 그 화면의 서치 스키마 출력과 같은 꼴이다 — 다른 페이지 모듈을 가져오지
 * 않으려고 여기서 다시 적는다. 그쪽에 값이 늘면 리다이렉트 라우트가 이 타입에 넘기는 자리에서 타입 검사가 멈춘다. */
export type LegacyMyWorksSearch = {
  type?: "character" | "story" | "unpublished";
  visibility?: Exclude<VisibilityFilter, "all">;
  sort?: "latest";
  q?: string;
};

/**
 * 옛 내 작품 주소의 조건을 스튜디오 홈 조건으로 옮긴다. 두 화면은 축이 달라 값을 그대로 넘길 수 없다 — 스튜디오에는
 * 유형 `unpublished` 와 공개 범위·정렬 축이 없어, 그대로 흘리면 스튜디오 스키마가 모르는 값으로 보고 "전체"로
 * 떨어뜨린다(초안만 보던 북마크가 소리 없이 모든 작품 목록이 된다).
 *
 * - 미등록(초안)은 유형이 아니라 상태 초안이다. 옛 화면도 미등록에서는 공개 범위를 무시했으므로 함께 와도 초안이 이긴다.
 * - 공개 범위 공개는 상태 공개 중이다. 링크 공개·비공개는 스튜디오에 대응하는 상태가 없어 버린다(전체).
 * - 정렬은 스튜디오에 축이 하나뿐이라 버린다. 검색어는 그대로 옮긴다. 묶음은 옛 화면에 없던 축이라 싣지 않는다.
 */
export function toStudioSearch(search: LegacyMyWorksSearch): StudioSearch {
  const studio: StudioSearch = {};
  if (search.type === "unpublished") studio.status = "draft";
  else {
    if (search.type !== undefined) studio.type = search.type;
    if (search.visibility === "public") studio.status = "public";
  }
  if (search.q !== undefined) studio.q = search.q;
  return studio;
}
