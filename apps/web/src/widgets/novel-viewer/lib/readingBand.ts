/** 띠 안에 걸친 문단 하나. `visibleHeight` 는 띠와 겹친 높이(px), `height` 는 문단 전체 높이(px). */
export type BandParagraph = { index: number; visibleHeight: number; height: number };

/** 문단이 "띠 안에 있다"고 셀 최소 겹침. 한 줄보다 짧게 잡아 짧은 문단도 셀 수 있게 하되, 문단 사이 간격 때문에
 * 앞 문단 아랫변이 띠 위 가장자리에 1px 도 안 되게 걸친 경우는 빼야 한다(그 조각을 세면 저장 자리가 한 문단
 * 앞으로 밀린다). */
export const MIN_VISIBLE_PX = 8;

/**
 * 지금 읽는 문단 — 띠 안에 충분히 걸친 문단 중 가장 앞 문단. 겹친 높이가 `MIN_VISIBLE_PX` 미만이면 세지 않는다(문단
 * 자체가 그보다 짧으면 통째로 들어와야 센다). 셀 문단이 없으면 `undefined` 다(호출부가 직전 문단을 그대로 둔다).
 */
export function toCurrentParagraphIndex(paragraphs: Iterable<BandParagraph>): number | undefined {
  let current: number | undefined;
  for (const { index, visibleHeight, height } of paragraphs) {
    if (visibleHeight < Math.min(MIN_VISIBLE_PX, height)) continue;
    if (current === undefined || index < current) current = index;
  }
  return current;
}

/**
 * 읽는 자리를 재는 띠(IntersectionObserver `rootMargin`). 아래쪽은 화면의 60% 를 잘라 위쪽 40% 만 남긴다. 위쪽은
 * 문단의 `scroll-margin-top`(+1px)만큼 잘라 낸다 — 저장된 자리로 되돌릴 때 그 문단 윗변이 화면 위에서 그만큼 아래에
 * 놓이는데, 띠가 화면 맨 위에서 시작하면 그 위 틈에 앞 문단 아랫변이 걸쳐 앞 문단을 지금 문단으로 세었다(열 때마다
 * 한 문단씩 밀렸다). 되돌린 문단 윗변은 띠 위 가장자리보다 1px 위라 그 문단은 띠에 걸친다.
 */
export function toReadingBandRootMargin(scrollMarginTopPx: number): string {
  return `-${Math.max(0, Math.ceil(scrollMarginTopPx)) + 1}px 0px -60% 0px`;
}

/** 문단 하나를 저장된 자리로 되돌릴 때의 창 스크롤 위치 — 문단 윗변이 화면 위에서 `scroll-margin-top` 만큼 아래에
 * 오게 한다(`scrollIntoView({block:"start"})` 와 같은 자리). */
export function toRestoreScrollTop({
  scrollY,
  elementTop,
  scrollMarginTop,
}: {
  scrollY: number;
  /** 문단의 `getBoundingClientRect().top`. */
  elementTop: number;
  scrollMarginTop: number;
}): number {
  return Math.max(0, scrollY + elementTop - scrollMarginTop);
}

/** 되돌리기가 화면에 반영됐는가 — 창 스크롤 위치가 목표(문서가 그보다 짧으면 갈 수 있는 끝)와 1px 안이다. 반영된
 * 것을 보기 전에는 읽는 자리를 재지 않는다: 그 사이 라우터가 창을 맨 위로 올리면 0번 문단을 지금 자리로 세어 저장된
 * 자리를 덮어쓴다. */
export function isScrollRestored({
  scrollY,
  targetTop,
  maxScrollY,
}: {
  scrollY: number;
  targetTop: number;
  /** `scrollHeight - innerHeight` — 창이 갈 수 있는 가장 아래. */
  maxScrollY: number;
}): boolean {
  const reachable = Math.max(0, Math.min(targetTop, maxScrollY));
  return Math.abs(scrollY - reachable) <= 1;
}

/** 열 때 읽던 자리로 되돌리기가 어떻게 됐나. `none` 은 그 화에 저장된 자리가 없다(처음 여는 화), `restored` 는
 * 저장된 자리가 화면에 반영됐다(맨 위가 그 자리인 경우 포함), `failed` 는 몇 프레임을 다시 놓아도 반영되지 않았다.
 * `unknown` 은 그 화의 자리를 응답에서 알 수 없었다(화별 자리를 싣기 전의 API — 서버에는 있을 수 있다). */
export type RestoreOutcome = "none" | "restored" | "failed" | "unknown";

/**
 * 읽는 자리를 언제부터 잴까. 되돌리기를 반영하지 못했거나 그 화의 자리를 알 수 없었을 때만 이용자가 스스로 스크롤한
 * 뒤부터이고, 나머지는 바로다.
 *
 * 못 했을 때 기다리는 이유: 화면이 저장된 자리가 아니라 맨 위에 있어, 보기만 하고 재면 0번 문단이 그 화의 저장된
 * 자리를 덮어쓴다. 자리를 알 수 없을 때도 서버에 있을지 모르는 자리를 같은 식으로 덮을 수 있다. 저장된 자리가 없는 화는 덮을 자리가 없어 바로 잰다 — 그래서 열기만 하고 떠나도 그 화의 0번 자리가
 * 남고 이어 읽기가 그 화를 가리킨다(화를 연 것을 읽기 시작으로 본다). 화가 짧아 마지막 문단이 처음부터 보이면 바로 다
 * 읽은 화가 되는 것도 같은 규칙이다.
 */
export function toTrackingStart(restore: RestoreOutcome): "now" | "afterUserScroll" {
  return restore === "failed" || restore === "unknown" ? "afterUserScroll" : "now";
}
