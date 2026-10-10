// 왼쪽 시트를 왼쪽으로 밀어 닫는 손짓의 판정. 수치는 web 소설 뷰어 페이지 모드의 쪽 끌기와 같은 값이다 — 한 앱
// 안에서 "끌기"의 손맛이 갈리지 않게. 거리 기준만 다르다(`toSheetSwipeRelease`).

/** 누른 자리에서 이만큼 움직인 순간 끌기인지 정한다. 그 안의 움직임은 탭(링크·버튼 누름)으로 남는다. */
export const SHEET_SWIPE_START_PX = 10

/** 손을 뗄 때의 속도를 이 시간 안의 움직임으로 잰다. 더 길면 멈췄다 놓은 손짓도 빠르게 튕긴 것으로 읽힌다. */
export const SHEET_SWIPE_VELOCITY_WINDOW_MS = 100

/** 이 속도(px/ms) 이상으로 튕기며 놓으면 거리와 무관하게 그 방향으로 친다. */
const SWIPE_VELOCITY_PX_PER_MS = 0.3

/** 시트 폭의 이 비율 이상 끌었으면 닫는다. 쪽 넘김(쪽 폭의 15%)보다 크게 잡는다 — 쪽 넘김은 바로 되돌릴 수 있는
 * 작은 이동이지만, 드로어를 닫으면 펼쳐 둔 목록·스크롤 위치 같은 열린 문맥을 버린다. */
const CLOSE_DISTANCE_RATIO = 1 / 3

/** 놓은 뒤 제자리로 맞춰 들어가는 시간. 시트 폭 전체를 갈 때 250ms 이고 남은 거리에 비례해 줄인다 — 거의 다 끌어
 * 놓은 시트가 고정 250ms 동안 들어오면 늘어져 보인다. 남은 거리가 아주 짧아도 순간이동이 아니라 맞춰 들어가는
 * 움직임으로 보이게 80ms 아래로는 줄이지 않는다. */
const SETTLE_MAX_MS = 250
const SETTLE_MIN_MS = 80

/** 끌기로 끝난 뗌 뒤의 click 을 막는 시간. 브라우저는 뗌 바로 뒤에 click 을 보내므로 이만큼이면 충분하고, 그보다
 * 늦게 오는 click 은 그 끌기의 것이 아니다 — 터치 스와이프는 click 을 만들지 않아 표시만 남는데, 그 표시가 한참
 * 뒤의 다른 click 을 삼키면 안 된다. */
const CLICK_SUPPRESS_MS = 100

export type SheetSwipeStart = "pending" | "drag" | "ignore"

/**
 * 누른 뒤의 움직임(누른 자리 기준, px)이 끌기인지. 10px 에 못 미치면 아직 모른다(`pending`). 10px 를 넘은 순간
 * 가로가 세로보다 크고 왼쪽이면 끌기이고, 그 밖(세로가 먼저이거나 둘이 같음, 오른쪽)은 이 누름 동안 끌기가 아니다
 * (`ignore` — 세로 스크롤은 브라우저가 맡는다). 호출부는 `pending` 이 아닌 답을 받으면 그 누름이 끝날 때까지 다시
 * 묻지 않는다.
 */
export function toSheetSwipeStart({ dx, dy }: { dx: number; dy: number }): SheetSwipeStart {
  if (Math.hypot(dx, dy) < SHEET_SWIPE_START_PX) return "pending"
  return dx < 0 && Math.abs(dx) > Math.abs(dy) ? "drag" : "ignore"
}

/** 끄는 동안 시트를 옮길 거리(px). 왼쪽으로는 손을 그대로 따라오고 오른쪽으로는 제자리에서 멈춘다(늘어나기 없음). */
export function toSheetSwipeOffset(dx: number): number {
  return Math.min(0, dx)
}

/**
 * 끌다가 놓았을 때 닫을지(`close`) 제자리로 돌아갈지(`settle`). 시트 폭의 1/3 이상 왼쪽으로 끌었거나 왼쪽으로
 * 0.3px/ms 이상 튕기며 놓으면 닫는다. 많이 끌었어도 오른쪽으로 그 속도 이상 튕기며 놓으면 되돌리려고 당긴 것이라
 * 돌아간다. 시트 폭을 모르면(0) 거리로는 닫지 않는다.
 *
 * @param velocityX 놓을 때의 가로 속도(px/ms, 오른쪽이 +). `toReleaseVelocity` 로 잰다.
 */
export function toSheetSwipeRelease({
  dx,
  velocityX,
  sheetWidth,
}: {
  dx: number
  velocityX: number
  sheetWidth: number
}): "close" | "settle" {
  if (velocityX >= SWIPE_VELOCITY_PX_PER_MS) return "settle"
  if (velocityX <= -SWIPE_VELOCITY_PX_PER_MS) return "close"
  const isFarEnough = sheetWidth > 0 && -toSheetSwipeOffset(dx) >= sheetWidth * CLOSE_DISTANCE_RATIO
  return isFarEnough ? "close" : "settle"
}

/** 놓은 뒤 남은 거리를 제자리로 맞춰 들어가는 시간(ms). 시트 폭을 모르면 움직일 기준이 없어 0 이다. */
export function toSheetSettleDurationMs({
  remainingPx,
  sheetWidth,
}: {
  remainingPx: number
  sheetWidth: number
}): number {
  if (sheetWidth <= 0) return 0
  const proportional = (SETTLE_MAX_MS * Math.abs(remainingPx)) / sheetWidth
  return Math.min(Math.max(proportional, SETTLE_MIN_MS), SETTLE_MAX_MS)
}

export type PointerSample = { x: number; time: number }

/** 놓기 직전 `SHEET_SWIPE_VELOCITY_WINDOW_MS` 안의 가로 속도(px/ms, 오른쪽이 +). 창 안에 앞선 표본이 없으면 0 이다. */
export function toReleaseVelocity(samples: readonly PointerSample[], last: PointerSample): number {
  const first = samples.find((sample) => last.time - sample.time <= SHEET_SWIPE_VELOCITY_WINDOW_MS)
  if (first === undefined || last.time <= first.time) return 0
  return (last.x - first.x) / (last.time - first.time)
}

/**
 * 끌기로 끝난 뗌 직후의 click 을 막을지 — 링크 위에서 시작한 끌기가 그 링크로 이동하지 않게. 키보드(Enter·Space)와
 * 보조기기의 활성화는 `detail` 이 0 인 click 이라 포인터 손짓과 무관하므로 막지 않는다. 끌기 표시가 없거나 표시 뒤
 * 시간이 지났으면 막지 않는다.
 *
 * @param suppressedAt 끌기로 끝난 뗌의 시각(ms, 이벤트 `timeStamp`).
 * @param detail `MouseEvent.detail` — 포인터로 누른 click 은 1 이상, 키보드·보조기기 활성화는 0 이다.
 */
export function shouldSuppressClickAfterSwipe({
  suppressedAt,
  clickAt,
  detail,
}: {
  suppressedAt: number | undefined
  clickAt: number
  detail: number
}): boolean {
  if (suppressedAt === undefined || detail === 0) return false
  return clickAt - suppressedAt <= CLICK_SUPPRESS_MS
}
