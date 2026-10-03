import { CONTENT_TYPE_LABEL, type ContentType } from "@/entities/content";

/** 홈 목록이 0건일 때의 한 문장. 조건이 걸렸든 아니든 같은 문장을 쓴다 — 걸린 조건은 바로 위 칩 줄이
 * 이미 보여 주므로 문장에서 되풀이하지 않고, 조건이 있을 때는 문장 아래 `필터 지우기`가 갈 길을 낸다. */
export const HOME_EMPTY_MESSAGE = "여기엔 아직 작품이 없어요.";

/** 무한스크롤 끝에 놓는 한 줄. 조건이 걸려 있으면 "모든 스토리"는 거짓이라 범위를 좁혀 말한다. */
export function toHomeListEndMessage(type: ContentType, isFiltered: boolean): string {
  const label = CONTENT_TYPE_LABEL[type];
  return isFiltered ? `조건에 맞는 ${label}를 모두 봤어요` : `모든 ${label}를 봤어요`;
}

/** 스크린리더 라이브 영역(`role="status"`)에 넣을 목록 상태 한 줄. 분기 순서는 화면(`HomeContentBody`)의
 * early return 순서와 같다 — 화면이 보여 주는 상태와 읽히는 상태가 갈리지 않게.
 *
 * 남은 페이지가 있는 동안은 "표시 중"을 붙여 총계를 주장하지 않는다(커서 페이징이라 총계 API가 없다).
 * 목록이 있는 채로 실패한 경우는 건수를 그대로 말한다 — 그 실패는 화면의 `role="alert"` 배너가 따로 알린다. */
export function toHomeListStatus({
  type,
  isFiltered,
  isPending,
  isError,
  itemCount,
  hasNextPage,
}: {
  type: ContentType;
  isFiltered: boolean;
  isPending: boolean;
  isError: boolean;
  itemCount: number;
  hasNextPage: boolean;
}): string {
  if (isPending) return "작품을 불러오는 중이에요";
  if (isError && itemCount === 0) return "목록을 불러오지 못했어요";
  if (itemCount === 0) return HOME_EMPTY_MESSAGE;
  if (hasNextPage) return `작품 ${itemCount}개 표시 중`;
  return `작품 ${itemCount}개, ${toHomeListEndMessage(type, isFiltered)}`;
}
