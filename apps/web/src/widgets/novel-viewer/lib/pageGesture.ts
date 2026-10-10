import { SHEET_SWIPE_VELOCITY_PX_PER_MS } from "@ai-character-chat/ui/lib/sheet-swipe";

import { shouldToggleChrome } from "./shouldToggleChrome";

/** 본문 탭 영역 — 창 폭의 왼쪽·오른쪽 4분의 1 이 이전·다음 쪽이고 가운데 절반이 바 토글이다. 조사한 뷰어들에서
 * 좌=이전·우=다음 배치는 확인했지만 세 영역의 비율을 밝힌 공개 근거는 찾지 못해 정한 값이라, 실기기에서 보고 조정할 수
 * 있다. 경계(정확히 25%·75%)는 덜 파괴적인 바 토글 쪽인 가운데다. */
const TAP_ZONE_RATIO = 0.25;

/** 탭이 아닌 손짓을 넘김으로 칠 기준 — 쪽 폭의 15% 이상 끌었거나 손을 뗄 때 0.3px/ms 이상으로 튕겼다. 짧게 튕기는
 * 스와이프와 천천히 끄는 끌기를 둘 다 받으면서, 그보다 작은 흔들림은 제자리로 돌려보낸다. 속도 기준은 왼쪽 드로어를
 * 밀어 닫는 손짓과 같은 값을 `@ai-character-chat/ui` 에서 가져온다(앱 안에서 튕김의 손맛이 갈리지 않게). 거리 기준은
 * 다르다 — 드로어는 닫으면 열린 문맥을 버려 1/3 이고, 쪽은 바로 되돌릴 수 있는 작은 이동이라 15%다. */
const SWIPE_DISTANCE_RATIO = 0.15;

/** 손을 뗀 뒤 맞춰 들어가는 시간. 한 화면 전체를 갈 때 넘김 전환과 같은 250ms 이고 남은 거리에 비례해 줄인다 — 거의
 * 다 끌어 놓은 쪽이 고정 250ms 동안 들어오면 늘어져 보인다. 남은 거리가 아주 짧아도 순간이동이 아니라 맞춰 들어가는
 * 움직임으로 보이게 80ms 아래로는 줄이지 않는다. */
const SETTLE_MAX_MS = 250;
const SETTLE_MIN_MS = 80;

export type TapZone = "previous" | "center" | "next";

export function toTapZone(clientX: number, viewportWidth: number): TapZone {
  if (clientX < viewportWidth * TAP_ZONE_RATIO) return "previous";
  if (clientX > viewportWidth * (1 - TAP_ZONE_RATIO)) return "next";
  return "center";
}

export type PageGestureInput = {
  /** 누른 자리에서 뗀 자리까지의 이동(px). */
  dx: number;
  dy: number;
  /** 누른 채 있던 시간(ms). */
  dt: number;
  /** 손을 뗄 때의 가로 속도(px/ms, 오른쪽이 +). */
  velocityX: number;
  /** 누른 자리의 가로 좌표와 창 폭 — 탭 영역을 고른다. */
  clientX: number;
  viewportWidth: number;
  /** 한 화면 폭(px). */
  pageWidth: number;
  /** 누른 자리가 링크·버튼처럼 스스로 동작하는 요소(또는 그 안)인가. */
  targetIsInteractive: boolean;
  isSettingsOpen: boolean;
  /** 핀치로 확대한 상태인가. 확대 중의 손짓은 확대한 화면을 둘러보는 것이라 쪽을 넘기지 않는다. */
  isZoomed: boolean;
};

export type PageGesture = "none" | "close-settings" | "toggle-chrome" | "previous" | "next" | "settle";

/**
 * 누름-뗌 한 번을 하나의 동작으로 가른다. 같은 뗌이 탭이면서 빠른 스와이프로도 읽힐 수 있어(9px 를 20ms 에 움직이면
 * 속도가 0.45px/ms 다) 한 함수에서 탭을 먼저 보고 하나만 낸다. 탭 기준은 스크롤 모드의 바 토글과 같은 거리·시간이다
 * — 페이지 모드는 본문 선택을 꺼 두어 선택 조건은 늘 참으로 넘긴다.
 *
 * 탭: 링크·버튼 위면 그 요소가 받으므로 아무것도 하지 않고, 보기 설정이 열려 있으면 어느 영역이든 설정만 닫는다(열린
 * 패널을 닫으려던 탭이 쪽을 넘기지 않게). 그 밖에는 영역대로 넘기거나 바를 여닫는다. 탭이 아니면 가로 이동이 세로
 * 이동 이상이고 거리나 속도 기준을 넘을 때 넘기고, 아니면 지금 화면으로 돌아간다(`settle`). 링크 위에서 시작한
 * 스와이프도 넘긴다. 많이 끌었어도 놓을 때 반대로 기준 속도 이상 튕겼으면 되돌리려고 당긴 것이라 제자리로 돌아간다.
 * 움직이지 않고 오래 누른 것과 쪽 폭을 아직 모를 때의 손짓은 아무것도 하지 않는다.
 */
export function toPageGesture({
  dx,
  dy,
  dt,
  velocityX,
  clientX,
  viewportWidth,
  pageWidth,
  targetIsInteractive,
  isSettingsOpen,
  isZoomed,
}: PageGestureInput): PageGesture {
  if (shouldToggleChrome({ dx, dy, dt, selectionCollapsed: true, targetIsInteractive: false })) {
    if (targetIsInteractive) return "none";
    if (isSettingsOpen) return "close-settings";
    const zone = toTapZone(clientX, viewportWidth);
    if (zone === "center") return "toggle-chrome";
    return isZoomed ? "none" : zone;
  }
  if (isZoomed || pageWidth <= 0 || (dx === 0 && dy === 0)) return "none";
  if (Math.abs(dx) < Math.abs(dy)) return "settle";
  if (Math.abs(velocityX) >= SHEET_SWIPE_VELOCITY_PX_PER_MS && Math.sign(velocityX) === -Math.sign(dx)) return "settle";
  const isFarEnough = Math.abs(dx) >= pageWidth * SWIPE_DISTANCE_RATIO;
  const isFlick = Math.abs(velocityX) >= SHEET_SWIPE_VELOCITY_PX_PER_MS && Math.sign(velocityX) === Math.sign(dx);
  if (!isFarEnough && !isFlick) return "settle";
  // 손가락을 왼쪽으로 밀면(dx < 0) 다음 쪽이 오른쪽에서 들어온다.
  return dx < 0 ? "next" : "previous";
}

/** 손을 뗀 뒤 남은 거리를 맞춰 들어가는 시간(ms). 쪽 폭을 아직 모르면 움직일 거리가 없어 0 이다. */
export function toSettleDurationMs({ remainingPx, pageWidth }: { remainingPx: number; pageWidth: number }): number {
  if (pageWidth <= 0) return 0;
  const proportional = (SETTLE_MAX_MS * Math.abs(remainingPx)) / pageWidth;
  return Math.min(Math.max(proportional, SETTLE_MIN_MS), SETTLE_MAX_MS);
}
