import type { ContentVisibility } from "@/entities/content";

/**
 * 발행 확인을 물어야 하는가 — 한 번도 발행하지 않은 작품(발행된 버전 0개)에만 묻는다. 재발행은 공개범위가 이미 작품에
 * 반영돼 있어(초안 저장이 공개범위를 바로 쓴다) 확인이 알려 줄 새 사실이 없으므로 곧장 발행한다.
 *
 * `publishedVersionCount` 가 `undefined` 면 이력을 확인하지 못한 것이다(조회 실패). 그때는 묻는다 — 재발행에서 한 번 더
 * 묻는 쪽이 첫 발행을 묻지 않고 보내는 쪽보다 덜 해롭다.
 */
export function needsFirstPublishConfirm(publishedVersionCount: number | undefined): boolean {
  return publishedVersionCount === undefined || publishedVersionCount === 0;
}

/** 첫 발행 확인창의 공개범위별 결과 문장. 공개범위 전환 확인창의 문장과 같은 골격("누가 볼 수 있는가")이고, 첫 발행이라
 * "빠지고"·"더 이상" 대신 처음부터 그렇다고 말한다. */
export const FIRST_PUBLISH_VISIBILITY_RESULT: Record<ContentVisibility, string> = {
  public: "발행하면 홈과 검색에 노출되고, 누구나 볼 수 있어요.",
  link: "발행해도 홈과 검색에는 나오지 않고, 링크를 가진 사람만 볼 수 있어요.",
  private: "발행해도 홈과 검색에는 나오지 않고, 나만 볼 수 있어요.",
};
