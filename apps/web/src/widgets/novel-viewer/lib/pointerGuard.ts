/** 끌기로 끝난 뗌 뒤의 click 을 막는 시간. 브라우저는 뗌 바로 뒤(같은 프레임 안팎)에 click 을 보내므로 이만큼이면
 * 충분하고, 그보다 늦게 오는 click 은 그 끌기의 것이 아니다 — 터치 스와이프는 click 을 만들지 않아 표시만 남는데,
 * 그 표시가 한참 뒤의 다른 click 을 삼키면 안 된다. */
const CLICK_SUPPRESS_MS = 100;

/** iOS 의 화면 가장자리 뒤로 가기 손짓이 시작되는 폭. */
const EDGE_GUARD_PX = 20;

/**
 * 끌기로 끝난 뗌 직후의 click 을 막을지. 키보드(Enter·Space)와 보조기기의 활성화는 `detail` 이 0 인 click 이라 포인터
 * 손짓과 무관하므로 막지 않는다. 끌기 표시가 없거나(`suppressedAt` 없음) 표시 뒤 시간이 지났으면 막지 않는다.
 */
export function shouldSuppressClick({
  suppressedAt,
  clickAt,
  detail,
}: {
  /** 끌기로 끝난 뗌의 시각(ms, 이벤트 `timeStamp`). */
  suppressedAt: number | undefined;
  clickAt: number;
  /** `MouseEvent.detail` — 포인터로 누른 click 은 누른 횟수(1 이상), 키보드·보조기기 활성화는 0 이다. */
  detail: number;
}): boolean {
  if (suppressedAt === undefined || detail === 0) return false;
  return clickAt - suppressedAt <= CLICK_SUPPRESS_MS;
}

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
