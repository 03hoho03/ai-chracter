/** 본문 탭 판별에 쓰는 한 번의 포인터 누름-뗌. `dx`·`dy` 는 누른 자리에서 뗀 자리까지의 이동(px), `dt` 는 누른 채
 * 있던 시간(ms)이다. */
export type ChromeTapGesture = {
  dx: number;
  dy: number;
  dt: number;
  /** 뗀 시점의 문서 선택이 비어 있는가(`Selection.isCollapsed`). */
  selectionCollapsed: boolean;
  /** 누른 자리가 링크·버튼처럼 스스로 동작하는 요소(또는 그 안)인가. */
  targetIsInteractive: boolean;
};

const MAX_TAP_DISTANCE_PX = 10;
const MAX_TAP_DURATION_MS = 300;

/**
 * 뷰어의 위·아래 바를 여닫을 "탭"인지 가른다. 읽는 중의 다른 손짓을 탭으로 잘못 읽으면 바가 제멋대로 뜨고 꺼지므로
 * 넷을 모두 만족할 때만 참이다 — 10px 이상 움직였으면 스크롤, 300ms 이상 눌렀으면 길게 누르기(문장 선택 시작),
 * 선택이 남아 있으면 방금 문장을 고른 것, 링크·버튼 위면 그 요소의 동작이다. 경계값(정확히 10px·300ms)은 탭이
 * 아니다.
 */
export function shouldToggleChrome({ dx, dy, dt, selectionCollapsed, targetIsInteractive }: ChromeTapGesture): boolean {
  return (
    Math.hypot(dx, dy) < MAX_TAP_DISTANCE_PX && dt < MAX_TAP_DURATION_MS && selectionCollapsed && !targetIsInteractive
  );
}
