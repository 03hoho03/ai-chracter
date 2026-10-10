/** iOS 의 화면 가장자리 뒤로 가기 손짓이 시작되는 폭. */
const EDGE_GUARD_PX = 20;

/**
 * 화면 가장자리에서 시작한 터치의 기본 동작을 막을지 — iOS 가장자리 스와이프(뒤로 가기)가 쪽 넘김과 부딪히지 않게.
 * 한 손가락일 때만 본다(두 손가락은 핀치 확대다). 링크·버튼 위의 터치는 막지 않는다 — 터치 기기는 넘김 버튼 자리가
 * 없어 좁은 폰에서는 쪽이 창 폭을 다 쓰고 글자가 가장자리 16px 부터 시작하므로, 화 머리 링크나 화 끝 "다음 화"
 * 버튼이 이 띠에 걸칠 수 있는데 막으면 그 탭의 click 이 사라진다.
 */
export function shouldGuardEdgeTouch({
  clientX,
  viewportWidth,
  touchCount,
  isOnInteractive,
}: {
  clientX: number;
  viewportWidth: number;
  touchCount: number;
  isOnInteractive: boolean;
}): boolean {
  if (touchCount !== 1 || isOnInteractive) return false;
  return clientX < EDGE_GUARD_PX || clientX > viewportWidth - EDGE_GUARD_PX;
}

/** 누른 채라고 알고 있던 마우스가 실제로는 버튼을 놓았다 — 본문 밖(겹쳐 뜬 바·넘김 버튼 위)에서 놓아 본문이 뗌을
 * 받지 못한 경우다. 터치·펜은 누름이 끝나면 뗌이나 취소가 반드시 오므로 마우스만 본다. */
export function isMouseReleasedElsewhere({ pointerType, buttons }: { pointerType: string; buttons: number }): boolean {
  return pointerType === "mouse" && (buttons & 1) === 0;
}
