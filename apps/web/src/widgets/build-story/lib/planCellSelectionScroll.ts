type CellSelectionScrollInput = {
  /** 고른 칸의 화면상 위 끝(px). */
  cellTop: number;
  /** 칸 상세 본문의 첫 행동 줄(이미지 넣기·바꾸기 버튼 묶음)의 화면상 아래 끝(px). */
  firstActionBottom: number;
  /** 상단바 아래로 실제로 보이는 높이(px). */
  availableHeight: number;
};

/**
 * 칸을 고른 뒤 무엇을 화면에 둘지. 칸부터 상세의 첫 행동 줄까지 한 화면에 들어가면 둘 다(고른 줄과 그 칸에서 할 일이
 * 함께 보여 다른 칸을 잘못 누르지 않는다), 안 들어가면 상세 머리를 위에 맞춘다 — 머리에 칸 썸네일과 이름이 있어 어느
 * 칸인지 거기서 확인되고, 그 아래 행동 줄도 화면에 든다. 머리까지만 재면 머리가 화면 바닥에 붙어 할 일이 화면 밖에 남는다.
 */
export function planCellSelectionScroll({
  cellTop,
  firstActionBottom,
  availableHeight,
}: CellSelectionScrollInput): "both" | "header" {
  return firstActionBottom - cellTop <= availableHeight ? "both" : "header";
}
