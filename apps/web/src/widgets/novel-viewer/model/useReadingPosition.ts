import { useQueryClient } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { useEffect, useRef, useState, type RefObject } from "react";

import {
  novelKeys,
  saveReadingPosition,
  sendReadingPositionKeepalive,
  type NovelReadingPositionRequest,
} from "@/entities/novel";

import {
  isScrollRestored,
  toCurrentParagraphIndex,
  toReadingBandRootMargin,
  toRestoreScrollTop,
  toTrackingStart,
  type BandParagraph,
} from "../lib/readingBand";
import { toRestoreParagraphIndex, type SavedReadingPosition } from "../lib/toRestoreParagraphIndex";

const SAVE_DEBOUNCE_MS = 3000;
/** 띠에 걸친 높이가 자라는 것도 따라가도록 겹침 비율 몇 단계마다 다시 알림을 받는다(0 하나면 들고 날 때만 온다). */
const READING_BAND_THRESHOLDS = [0, 0.05, 0.1, 0.25, 0.5, 0.75, 1];
/** 되돌리기가 반영됐는지 다시 보는 프레임 수(약 0.5초). 그 안에 반영되지 않으면 이용자가 스스로 스크롤할 때까지 재지
 * 않는다. */
const MAX_RESTORE_FRAMES = 30;

type UseReadingPositionOptions = {
  novelId: string;
  chapterId: string;
  revisionId: string;
  paragraphCount: number;
  /** 이 화에 저장된 읽은 자리. 소설의 마지막 읽은 자리가 이 화일 때만 있다. */
  saved: SavedReadingPosition | undefined;
  /** 이 화를 이미 다 읽었는가(그때는 다시 읽어도 다 읽은 화로 남는다 — 서버도 되돌리지 않는다). */
  wasFinished: boolean;
  /** `data-paragraph-index` 문단들을 담은 요소. */
  containerRef: RefObject<HTMLElement | null>;
};

function positionKey(body: NovelReadingPositionRequest): string {
  return `${body.revisionId}:${body.paragraphIndex}/${body.paragraphCount}:${body.finished ? 1 : 0}`;
}

/**
 * 화를 읽는 자리를 서버에 남기고, 열 때 한 번 그 자리로 되돌린다.
 *
 * - **되돌리기**: 한 번만, 저장된 자리(그 뒤 화가 고쳐졌으면 문단 수 비율로 옮긴 자리)의 문단을 화면 맨 위로
 *   스크롤한다. **라우터가 이 이동을 다 끝낸 뒤에** 한다 — 라우터는 경로가 바뀐 이동 뒤 창을 맨 위로 올리는데, 그
 *   시점은 새 화면이 마운트된 커밋이 아니라 그 뒤 라우터가 이동을 "해결됨"으로 적는 커밋(`resolvedLocation` 갱신 →
 *   `onRendered`)이다. 데이터가 캐시에 있으면 읽기 화면이 그보다 먼저 마운트돼, 마운트 직후(다음 프레임)에 되돌리면
 *   곧이어 맨 위로 덮였다(작품 정보 → 이어 읽기에서 실측). 그래서 이동이 해결된 커밋 뒤 다음 프레임에 되돌리고,
 *   그래도 덮일 수 있으니 반영됐는지 몇 프레임 다시 보며 다시 놓는다. 링크마다 `resetScroll: false` 를 다는 길도
 *   있지만, 그러면 읽기 화면으로 오는 모든 길(목차·이전/다음 화·이어 읽기, 그리고 다음에 생길 길)이 그 옵션을
 *   기억해야 하고 브라우저 뒤로 가기에는 달 자리가 없다 — 한 곳(여기)에서 순서를 지키는 쪽이 빠짐이 없다.
 *   `scrollIntoView` 가 아니라 창 스크롤 위치를 직접 준다 — Chrome 은 `scrollIntoView` 대상으로 순차 포커스 시작점을
 *   옮겨, 되돌린 뒤 첫 Tab 이 "메뉴 열기"가 아니라 그 아래 첫 링크로 가며 화면이 튄다.
 * - **저장 가드**: 되돌린 자리가 화면에 반영된 것을 확인한 뒤에야 지금 문단을 재기 시작한다(`isScrollRestored`). 재지
 *   않으면 저장할 것도 없어 디바운스 저장·keepalive 모두 나가지 않는다 — 맨 위로 덮인 화면의 0번 문단이 저장된
 *   자리를 덮어쓰지 않게. 반영을 끝내 못 보면 이용자가 스스로 스크롤한 뒤부터 잰다. 되돌릴 자리가 없는 화도
 *   이용자가 스크롤한 뒤부터 잰다 — 지금은 소설의 마지막 읽은 자리 하나만 받아, 다른 화는 서버에 자리가 있어도 맨
 *   위에서 열리므로 보기만 하고 재면 그 화의 자리를 0 으로 덮는다(화마다 자리를 받아 되돌리게 되면 이 조건을 푼다).
 * - **지금 문단**: 화면 위쪽 띠에 충분히 걸친 문단 중 가장 앞 문단(`toCurrentParagraphIndex`). 띠 위쪽은 문단의
 *   `scroll-margin-top` 만큼 잘라 되돌린 자리 바로 위 틈의 앞 문단을 세지 않는다. 마지막 문단이 화면에 들어오면 다
 *   읽음이다.
 * - **저장**: 자리가 바뀌면 3초 뒤 저장한다(스크롤하는 동안 요청이 쏟아지지 않게). 페이지가 숨거나(탭 전환·앱
 *   전환·닫기) 이 화를 떠날 때(다른 화로 옮김 포함) 기다리던 저장을 `keepalive` 로 바로 보낸다 — 그때는 보통 요청이
 *   끊긴다.
 * - **떠날 때**: 저장 응답에 본문이 없어 상세 캐시의 이어 읽기·읽음 표시가 낡는다 — 날아가던 저장과 마지막 저장이
 *   모두 끝난 뒤 상세를 다시 받게 표시해 작품 정보 화면이 돌아왔을 때 맞는 표시를 보게 한다(먼저 다시 받으면 저장
 *   전 값을 받아 낡은 채 남는다).
 */
export function useReadingPosition({
  novelId,
  chapterId,
  revisionId,
  paragraphCount,
  saved,
  wasFinished,
  containerRef,
}: UseReadingPositionOptions) {
  const queryClient = useQueryClient();
  const pendingRef = useRef<NovelReadingPositionRequest | undefined>(undefined);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastKeyRef = useRef<string | undefined>(undefined);
  const inflightRef = useRef<Promise<void>>(Promise.resolve());
  // 라우터가 이 이동을 끝냈는가(지금 주소가 해결된 주소이고 진행 중인 이동이 없다). 한 번 참이 되면 참으로 남긴다 —
  // 이 화면을 떠나는 다음 이동이 시작돼 거짓이 돼도 되돌리기·재기를 다시 하지 않게.
  const isRouteResolved = useRouterState({
    select: (state) => state.status === "idle" && state.resolvedLocation?.href === state.location.href,
  });
  const [hasRouteSettled, setHasRouteSettled] = useState(isRouteResolved);
  if (isRouteResolved && !hasRouteSettled) setHasRouteSettled(true);

  useEffect(() => {
    if (!hasRouteSettled) return;
    const root = containerRef.current;
    // 문단이 없는 화는 서버가 자리를 받지 않는다(문단 번호는 문단 수보다 작아야 한다).
    if (root === null || paragraphCount === 0) return;
    const container: HTMLElement = root;

    let currentIndex: number | undefined;
    let isFinished = wasFinished;
    const visible = new Map<number, BandParagraph>();
    const observers: IntersectionObserver[] = [];

    function cancelTimer() {
      if (timerRef.current === undefined) return;
      clearTimeout(timerRef.current);
      timerRef.current = undefined;
    }

    function takePending(): NovelReadingPositionRequest | undefined {
      cancelTimer();
      const body = pendingRef.current;
      pendingRef.current = undefined;
      return body;
    }

    function record() {
      if (currentIndex === undefined) return;
      const body = { paragraphIndex: currentIndex, paragraphCount, revisionId, finished: isFinished };
      const key = positionKey(body);
      if (key === lastKeyRef.current) return;
      lastKeyRef.current = key;
      pendingRef.current = body;
      cancelTimer();
      timerRef.current = setTimeout(() => {
        const pending = takePending();
        if (pending !== undefined) inflightRef.current = saveReadingPosition(novelId, chapterId, pending);
      }, SAVE_DEBOUNCE_MS);
    }

    function flushKeepalive(): Promise<void> {
      const pending = takePending();
      return pending === undefined ? Promise.resolve() : sendReadingPositionKeepalive(novelId, chapterId, pending);
    }

    function handleVisibilityChange() {
      if (document.visibilityState === "hidden") void flushKeepalive();
    }

    function handlePageHide() {
      void flushKeepalive();
    }

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
          currentIndex = next;
          record();
        },
        { rootMargin: toReadingBandRootMargin(scrollMarginTopOf(paragraphs.item(0))), threshold: READING_BAND_THRESHOLDS },
      );
      for (const paragraph of paragraphs) bandObserver.observe(paragraph);
      observers.push(bandObserver);

      const lastParagraph = paragraphs.item(paragraphs.length - 1);
      const endObserver = new IntersectionObserver((entries) => {
        if (isFinished || !entries.some((entry) => entry.isIntersecting)) return;
        isFinished = true;
        record();
      });
      endObserver.observe(lastParagraph);
      observers.push(endObserver);
    }

    const restoredIndex = saved === undefined ? 0 : toRestoreParagraphIndex(saved, paragraphCount);
    // 저장된 자리와 같은 값은 다시 보내지 않는다.
    if (saved !== undefined) {
      lastKeyRef.current = positionKey({ paragraphIndex: restoredIndex, paragraphCount, revisionId, finished: wasFinished });
    }

    const target = restoredIndex > 0 ? container.querySelector<HTMLElement>(`[data-paragraph-index="${restoredIndex}"]`) : null;
    let frame: number | undefined;
    let isTracking = false;

    function startTrackingOnce() {
      if (isTracking) return;
      isTracking = true;
      window.removeEventListener("scroll", handleUserScroll);
      startTracking(container);
    }

    // 이용자가 스스로 스크롤하면 그 자리는 이용자가 고른 자리라 재기 시작한다(되돌리기를 못 했거나 되돌릴 자리가 없는
    // 화 — `toTrackingStart`).
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
          maxScrollY: document.documentElement.scrollHeight - window.innerHeight,
        });
        if (!isRestored && attempt + 1 < MAX_RESTORE_FRAMES) attemptRestore(element, attempt + 1);
        else startTrackingWhen(toTrackingStart({ hasRestoreTarget: true, isRestored }));
      });
    }

    frame = requestAnimationFrame(() => {
      frame = undefined;
      if (target === null) startTrackingWhen(toTrackingStart({ hasRestoreTarget: false, isRestored: false }));
      else attemptRestore(target, 0);
    });

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("pagehide", handlePageHide);
    return () => {
      if (frame !== undefined) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", handleUserScroll);
      for (const observer of observers) observer.disconnect();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("pagehide", handlePageHide);
      void Promise.all([inflightRef.current, flushKeepalive()]).then(() =>
        queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) }),
      );
    };
    // 화·개정이 바뀌면 읽기 화면이 새로 마운트된다(호출부가 화 id 로 key 를 준다). 저장된 자리는 열 때 한 번만 쓴다 —
    // 라우터가 이동을 끝낸 순간 한 번 돈다(`hasRouteSettled` 는 한 번 참이면 바뀌지 않는다).
  }, [hasRouteSettled]);
}

/** 문단의 계산된 `scroll-margin-top`(px). 안전 영역이 더해진 값이라 CSS 에서 읽는다. */
function scrollMarginTopOf(element: Element): number {
  return Number.parseFloat(getComputedStyle(element).scrollMarginTop) || 0;
}
