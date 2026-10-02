type CellSelectionScrollInput = {
  /** 고른 칸의 화면상 위 끝(px). */
  cellTop: number;
  /** 칸 상세 본문의 첫 행동 줄(이미지 넣기·바꾸기 버튼 묶음)의 화면상 아래 끝(px). */
  firstActionBottom: number;
  /** 상단바 아래로 실제로 보이는 높이(px). */
  availableHeight: number;
  /** 고른 칸에 아직 이미지가 없는지. 빈 칸 상세는 행동 줄 아래에 입력칸이 없다. */
  isEmpty: boolean;
};

/**
 * 칸을 고른 뒤 무엇을 화면에 둘지. 칸부터 상세의 첫 행동 줄까지 한 화면에 들어가면 둘 다(고른 줄과 그 칸에서 할 일이
 * 함께 보여 다른 칸을 잘못 누르지 않는다). 안 들어가면 상세 머리의 칸 썸네일과 이름이 어느 칸인지 알려 주고, 나머지는
 * 칸이 비었는지에 따라 갈린다.
 * - 빈 칸은 첫 행동 줄을 화면 바닥에 맞춘다. 행동 줄 아래에 입력칸이 없어 머리를 위에 맞추면 스크롤 끝에 걸리기
 *   쉽고, 할 일을 보이는 데 필요한 것보다 더 내려가 표가 그만큼 위로 밀려난다. 바닥에 맞추면 바로 위의 머리도 함께
 *   보이고, 남는 위쪽에 표가, 되도록 고른 칸까지 남는다.
 * - 채운 칸은 머리를 위에 맞춘다. 미리보기가 머리와 행동 줄 사이에 있어 둘이 멀다. 그래서 이 갈래에 오는 좁은 화면에서는
 *   행동 줄을 바닥에 맞춰도 고른 칸까지 닿지 못하고, 행동 줄 아래의 상황 설명·해금 힌트 입력칸만 화면 밖으로 밀려난다.
 */
export function planCellSelectionScroll({
  cellTop,
  firstActionBottom,
  availableHeight,
  isEmpty,
}: CellSelectionScrollInput): "both" | "action" | "header" {
  if (firstActionBottom - cellTop <= availableHeight) return "both";
  return isEmpty ? "action" : "header";
}
