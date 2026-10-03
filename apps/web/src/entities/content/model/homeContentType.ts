import type { ContentListSort, ContentType } from "./content";

/** 홈 URL의 `?type=` 값. 기본 유형(스토리)은 멤버에 없다 — 파라미터의 부재가 곧 스토리라서,
 * 이 타입으로 `<Link search>`·`navigate`를 쓰면 `?type=story`가 타입 단계에서 막힌다. */
export type HomeTypeParam = Exclude<ContentType, "story">;

/** 홈의 기본 유형은 스토리다. 공개 재고가 스토리 쪽에 몰려 있어서다(2026-10 운영 기준 스토리 약 31편,
 * 캐릭터 3편) — 처음 온 사람이 파라미터 없는 `/`에서 캐릭터 세 장만 보고 떠나지 않게 한다. 재고 비율이
 * 뒤집히면 이 함수와 `toHomeTypeParam`, 홈 서치 스키마의 `.exclude([...])`를 함께 바꾼다. */
export function resolveHomeContentType(param: HomeTypeParam | undefined): ContentType {
  return param ?? "story";
}

export function toHomeTypeParam(type: ContentType): HomeTypeParam | undefined {
  return type === "story" ? undefined : type;
}

/** 홈 유형을 바꿀 때 다음 홈 search. **정렬만 들고 가고 장르·검색어·작가·해시태그는 버린다** —
 * 캐릭터 장르 대부분이 0건이라 필터를 끌고 가면 전환 직후 빈 화면이 흔해진다. 정렬은 거르지 않고
 * 순서만 바꾸는 축이라 어느 유형에서도 빈 화면을 만들지 않는다.
 *
 * 헤더 유형 탭(홈 안·밖 전부)과 홈 첫 행의 유형 전환이 이 함수 하나를 쓴다 — 두 곳에 규칙을 따로 두면
 * 한쪽만 고쳐지는 게 이 저장소의 실패 모드다. 스토리와 비어 있는 정렬은 키 자체를 싣지 않는다. */
export function toHomeTypeSwitchSearch(
  nextType: ContentType,
  sort: ContentListSort | undefined,
): { type?: HomeTypeParam; sort?: ContentListSort } {
  const type = toHomeTypeParam(nextType);
  return { ...(type && { type }), ...(sort && { sort }) };
}
