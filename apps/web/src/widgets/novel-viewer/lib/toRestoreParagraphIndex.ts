export type SavedReadingPosition = {
  /** 저장할 때 읽고 있던 문단(0부터). */
  paragraphIndex: number;
  /** 저장할 때 그 화 본문의 문단 수. */
  paragraphCount: number;
};

/**
 * 저장된 읽은 위치를 지금 본문의 문단 인덱스로 옮긴다. 저장한 뒤 화가 고쳐져 문단 수가 달라졌으면 같은 인덱스는 다른
 * 장면을 가리키므로, 화 안에서 같은 비율 지점(`round(인덱스 × 지금 문단 수 / 그때 문단 수)`)으로 근사한다. 문단 수가
 * 같으면 인덱스를 그대로 쓴다. 결과는 언제나 지금 본문 안(`0 … 문단 수 - 1`)으로 잘라 낸다 — 본문이 짧아졌거나 저장값이
 * 이상해도 없는 문단으로 스크롤하지 않는다. 본문이 비었으면 0.
 */
export function toRestoreParagraphIndex(saved: SavedReadingPosition, currentParagraphCount: number): number {
  if (currentParagraphCount <= 0) return 0;

  const lastIndex = currentParagraphCount - 1;
  const index =
    saved.paragraphCount > 0 && saved.paragraphCount !== currentParagraphCount
      ? Math.round((saved.paragraphIndex * currentParagraphCount) / saved.paragraphCount)
      : saved.paragraphIndex;

  return Math.min(Math.max(index, 0), lastIndex);
}
