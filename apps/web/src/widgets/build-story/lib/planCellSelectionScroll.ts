type CellSelectionScrollInput = {
  /** 고른 칸의 화면상 위 끝(px). */
  cellTop: number;
  /** 칸 상세 머리(이름 줄과 표기 줄)의 화면상 아래 끝(px). */
  headerBottom: number;
  /** 상단바 아래로 실제로 보이는 높이(px). */
  availableHeight: number;
};

/**
 * 칸을 고른 뒤 무엇을 화면에 둘지. 칸과 상세 머리가 한 화면에 들어가면 둘 다(고른 줄과 상세가 함께 보여 다른 칸을
 * 잘못 누르지 않는다), 안 들어가면 상세 머리를 우선한다 — 머리에 칸 썸네일과 이름이 있어 어느 칸인지 거기서 확인된다.
 */
export function planCellSelectionScroll({
  cellTop,
  headerBottom,
  availableHeight,
}: CellSelectionScrollInput): "both" | "header" {
  return headerBottom - cellTop <= availableHeight ? "both" : "header";
}
