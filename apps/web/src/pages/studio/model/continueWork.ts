import type { WorkItem } from "@/entities/work";

/**
 * 이어 만들기 카드에 올릴 작품 하나 — 목록 순서(마지막 편집 순)에서 첫 번째 "끝나지 않은 일". 초안, 수정본 있는
 * 발행작(공개 범위 무관), 그리고 소설 영역이 열린 계정의 소설이다. 수정본 없는 발행작과 이용제한 작품은 고를 할 일이
 * 수정뿐이라 넘긴다.
 *
 * 찾는 범위는 조건 없는 목록의 첫 페이지(24건)뿐이다. 최근 24건이 모두 손댈 것 없는 발행작이면 카드가 없다 — 더 찾으려면
 * 서버 조회가 하나 더 필요해서 받아들인 한계다.
 */
export function pickContinueWork(items: readonly WorkItem[], isNovelAreaVisible: boolean): WorkItem | undefined {
  return items.find((item) => {
    if (item.kind === "novel") return isNovelAreaVisible;
    if (!item.hasPublished) return true;
    return item.hasUnpublishedChanges && item.moderationStatus !== "restricted";
  });
}
