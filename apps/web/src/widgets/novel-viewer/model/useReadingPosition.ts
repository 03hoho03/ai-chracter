import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, type RefObject } from "react";

import {
  novelKeys,
  saveReadingPosition,
  sendReadingPositionKeepalive,
  type NovelReadingPositionRequest,
} from "@/entities/novel";

import {
  toCurrentParagraphIndex,
  toReadingBandRootMargin,
  toRestoreScrollTop,
  type BandParagraph,
} from "../lib/readingBand";
import { toRestoreParagraphIndex, type SavedReadingPosition } from "../lib/toRestoreParagraphIndex";

const SAVE_DEBOUNCE_MS = 3000;
/** 띠에 걸친 높이가 자라는 것도 따라가도록 겹침 비율 몇 단계마다 다시 알림을 받는다(0 하나면 들고 날 때만 온다). */
const READING_BAND_THRESHOLDS = [0, 0.05, 0.1, 0.25, 0.5, 0.75, 1];

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
 * - **되돌리기**: 마운트 뒤 한 번만, 저장된 자리(그 뒤 화가 고쳐졌으면 문단 수 비율로 옮긴 자리)의 문단을 화면 맨 위로
 *   스크롤한다. 다음 프레임에 하는 이유는 라우터가 경로가 바뀐 이동 뒤 창을 맨 위로 올리기 때문이다 — 그보다 먼저
 *   스크롤하면 도로 맨 위가 된다. `scrollIntoView` 가 아니라 창 스크롤 위치를 직접 준다 — Chrome 은
 *   `scrollIntoView` 대상으로 순차 포커스 시작점을 옮겨, 되돌린 뒤 첫 Tab 이 "메뉴 열기"가 아니라 그 아래 첫 링크로
 *   가며 화면이 튄다. 되돌린 뒤에야 지금 문단을 재기 시작한다(그 전의 0번 문단을 저장하지 않게).
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

  useEffect(() => {
    const container = containerRef.current;
    // 문단이 없는 화는 서버가 자리를 받지 않는다(문단 번호는 문단 수보다 작아야 한다).
    if (container === null || paragraphCount === 0) return;

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

    const frame = requestAnimationFrame(() => {
      const target = restoredIndex > 0 ? container.querySelector<HTMLElement>(`[data-paragraph-index="${restoredIndex}"]`) : null;
      if (target !== null) {
        window.scrollTo({
          top: toRestoreScrollTop({
            scrollY: window.scrollY,
            elementTop: target.getBoundingClientRect().top,
            scrollMarginTop: scrollMarginTopOf(target),
          }),
          behavior: "instant",
        });
      }
      startTracking(container);
    });

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("pagehide", handlePageHide);
    return () => {
      cancelAnimationFrame(frame);
      for (const observer of observers) observer.disconnect();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("pagehide", handlePageHide);
      void Promise.all([inflightRef.current, flushKeepalive()]).then(() =>
        queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) }),
      );
    };
    // 화·개정이 바뀌면 읽기 화면이 새로 마운트된다(호출부가 화 id 로 key 를 준다). 저장된 자리는 열 때 한 번만 쓴다.
  }, []);
}

/** 문단의 계산된 `scroll-margin-top`(px). 안전 영역이 더해진 값이라 CSS 에서 읽는다. */
function scrollMarginTopOf(element: Element): number {
  return Number.parseFloat(getComputedStyle(element).scrollMarginTop) || 0;
}
