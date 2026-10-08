import { useEffect, type RefObject } from "react";

import {
  isScrollRestored,
  toCurrentParagraphIndex,
  toReadingBandRootMargin,
  toRestoreScrollTop,
  toSavedParagraphIndex,
  toTrackingStart,
  type BandParagraph,
} from "../lib/readingBand";
import type { ReadingPositionSession } from "./useReadingPosition";

/** 띠에 걸친 높이가 자라는 것도 따라가도록 겹침 비율 몇 단계마다 다시 알림을 받는다(0 하나면 들고 날 때만 온다). */
const READING_BAND_THRESHOLDS = [0, 0.05, 0.1, 0.25, 0.5, 0.75, 1];
/** 되돌리기가 반영됐는지 다시 보는 프레임 수(약 0.5초). 그 안에 반영되지 않으면 이용자가 스스로 스크롤할 때까지 재지
 * 않는다. */
const MAX_RESTORE_FRAMES = 30;

type UseScrollReadingTrackerOptions = {
  session: ReadingPositionSession;
  paragraphCount: number;
  /** `data-paragraph-index` 문단들을 담은 요소. */
  containerRef: RefObject<HTMLElement | null>;
};

/**
 * 창 세로 스크롤로 읽는 본문에서, 붙을 때 한 번 읽던 자리로 되돌리고 지금 문단을 재서 `session` 에 알린다. 저장·떠남
 * 처리는 화 단위 `useReadingPosition` 이 맡는다.
 *
 * - **되돌리기**: 한 번만, 되돌릴 문단(`session.toRestoreTarget`)을 화면 맨 위로 스크롤한다. 라우터가 이동을 끝낸 뒤
 *   (`hasRouteSettled`) 다음 프레임에 놓고, 그래도 라우터의 맨 위 올리기에 덮일 수 있으니 반영됐는지 몇 프레임 다시
 *   보며 다시 놓는다. `scrollIntoView` 가 아니라 창 스크롤 위치를 직접 준다 — Chrome 은 `scrollIntoView` 대상으로
 *   순차 포커스 시작점을 옮겨, 되돌린 뒤 첫 Tab 이 "메뉴 열기"가 아니라 그 아래 첫 링크로 가며 화면이 튄다.
 * - **재기 시작**: 되돌린 자리가 화면에 반영된 것을 확인한 뒤에야 지금 문단을 재기 시작한다(`isScrollRestored`) — 맨
 *   위로 덮인 화면의 0번 문단이 저장된 자리를 덮어쓰지 않게. 반영을 끝내 못 보면 이용자가 스스로 스크롤한 뒤부터
 *   잰다. 저장된 자리가 없는 화(처음 여는 화)와 저장된 자리가 맨 위인 화는 덮을 것이 없어 바로 잰다
 *   (`toTrackingStart`). 화별 자리를 싣기 전의 API 응답이라 그 화의 자리를 모르면 맨 위에서 재지 않고 이용자가
 *   스크롤한 뒤부터 잰다.
 * - **지금 문단**: 화면 위쪽 띠에 충분히 걸친 문단 중 가장 앞 문단(`toCurrentParagraphIndex`). 띠 위쪽은 문단의
 *   `scroll-margin-top` 만큼 잘라 되돌린 자리 바로 위 틈의 앞 문단을 세지 않는다. 마지막 문단이 화면에 들어오면 다
 *   읽음이다. 마지막 화면 안의 자리로 되돌려 창이 문서 끝에 막혔으면, 끝에 있는 동안은 띠에 걸린 더 앞 문단 대신
 *   되돌린 문단을 지금 문단으로 둔다(`toSavedParagraphIndex`) — 스크롤하지 않았는데 자리가 앞당겨지지 않게.
 */
export function useScrollReadingTracker({ session, paragraphCount, containerRef }: UseScrollReadingTrackerOptions) {
  const { hasRouteSettled } = session;

  useEffect(() => {
    if (!hasRouteSettled) return;
    const root = containerRef.current;
    // 문단이 없는 화는 서버가 자리를 받지 않는다(문단 번호는 문단 수보다 작아야 한다).
    if (root === null || paragraphCount === 0) return;
    const container: HTMLElement = root;

    const visible = new Map<number, BandParagraph>();
    const observers: IntersectionObserver[] = [];

    function startTracking(root: HTMLElement) {
      const paragraphs = root.querySelectorAll<HTMLElement>("[data-paragraph-index]");
      const bandObserver = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            const index = Number(entry.target.getAttribute("data-paragraph-index"));
            if (entry.isIntersecting) {
              visible.set(index, {
                index,
                visibleHeight: entry.intersectionRect.height,
                height: entry.boundingClientRect.height,
              });
            } else {
              visible.delete(index);
            }
          }
          // 띠가 문단 사이 틈에 걸려 셀 문단이 없으면 직전 문단을 그대로 둔다.
          const next = toCurrentParagraphIndex(visible.values());
          if (next === undefined) return;
          session.reportParagraph(
            toSavedParagraphIndex({
              measuredIndex: next,
              restoredIndex,
              scrollY: window.scrollY,
              maxScrollY: maxScrollYOf(),
            }),
          );
        },
        { rootMargin: toReadingBandRootMargin(scrollMarginTopOf(paragraphs.item(0))), threshold: READING_BAND_THRESHOLDS },
      );
      for (const paragraph of paragraphs) bandObserver.observe(paragraph);
      observers.push(bandObserver);

      const lastParagraph = paragraphs.item(paragraphs.length - 1);
      const endObserver = new IntersectionObserver((entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        session.reportFinished();
      });
      endObserver.observe(lastParagraph);
      observers.push(endObserver);
    }

    const { index: restoredIndex, basis } = session.toRestoreTarget();

    const target = restoredIndex > 0 ? container.querySelector<HTMLElement>(`[data-paragraph-index="${restoredIndex}"]`) : null;
    let frame: number | undefined;
    let isTracking = false;

    function startTrackingOnce() {
      if (isTracking) return;
      isTracking = true;
      window.removeEventListener("scroll", handleUserScroll);
      session.reportTrackingStarted();
      startTracking(container);
    }

    // 이용자가 스스로 스크롤하면 그 자리는 이용자가 고른 자리라 재기 시작한다(되돌리기를 못 한 화 — `toTrackingStart`).
    function handleUserScroll() {
      startTrackingOnce();
    }

    function startTrackingWhen(start: "now" | "afterUserScroll") {
      if (start === "now") startTrackingOnce();
      else window.addEventListener("scroll", handleUserScroll, { passive: true, once: true });
    }

    function restoreTop(element: HTMLElement): number {
      return toRestoreScrollTop({
        scrollY: window.scrollY,
        elementTop: element.getBoundingClientRect().top,
        scrollMarginTop: scrollMarginTopOf(element),
      });
    }

    function attemptRestore(element: HTMLElement, attempt: number) {
      const top = restoreTop(element);
      window.scrollTo({ top, behavior: "instant" });
      frame = requestAnimationFrame(() => {
        frame = undefined;
        const isRestored = isScrollRestored({
          scrollY: window.scrollY,
          targetTop: restoreTop(element),
          maxScrollY: maxScrollYOf(),
        });
        if (!isRestored && attempt + 1 < MAX_RESTORE_FRAMES) attemptRestore(element, attempt + 1);
        else startTrackingWhen(toTrackingStart(isRestored ? "restored" : "failed"));
      });
    }

    frame = requestAnimationFrame(() => {
      frame = undefined;
      if (target !== null) {
        attemptRestore(target, 0);
        return;
      }
      // 되돌릴 문단을 찾지 못한 것은 반영하지 못한 것과 같다(맨 위에서 재면 저장된 자리를 덮는다). 저장된 자리가 맨
      // 위면 라우터가 이미 맨 위로 올려 둔 그 자리다.
      if (restoredIndex > 0) startTrackingWhen(toTrackingStart("failed"));
      else if (basis === "saved") startTrackingWhen(toTrackingStart("restored"));
      else startTrackingWhen(toTrackingStart(basis));
    });

    return () => {
      if (frame !== undefined) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", handleUserScroll);
      for (const observer of observers) observer.disconnect();
    };
    // 이 본문이 붙어 있는 동안 한 번만 되돌리고 잰다(`hasRouteSettled` 는 한 번 참이면 바뀌지 않는다). 화를 열 때는
    // 라우터가 이동을 끝낸 순간, 같은 화 안에서 본문을 바꿔 끼울 때는 붙는 순간 돈다.
  }, [hasRouteSettled]);
}

/** 창이 갈 수 있는 가장 아래 스크롤 위치. */
function maxScrollYOf(): number {
  return document.documentElement.scrollHeight - window.innerHeight;
}

/** 문단의 계산된 `scroll-margin-top`(px). 안전 영역이 더해진 값이라 CSS 에서 읽는다. */
function scrollMarginTopOf(element: Element): number {
  return Number.parseFloat(getComputedStyle(element).scrollMarginTop) || 0;
}
