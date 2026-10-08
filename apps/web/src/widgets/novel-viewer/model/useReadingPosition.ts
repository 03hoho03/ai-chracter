import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, type RefObject } from "react";

import {
  novelKeys,
  saveReadingPosition,
  sendReadingPositionKeepalive,
  type NovelReadingPositionRequest,
} from "@/entities/novel";

import { toRestoreParagraphIndex, type SavedReadingPosition } from "../lib/toRestoreParagraphIndex";

const SAVE_DEBOUNCE_MS = 3000;
/** "지금 읽는 문단"을 가르는 띠 — 화면 위쪽 40%. 그 띠에 걸린 문단 중 가장 앞 문단이 지금 문단이다. 바가 숨은 상태
 * 기준이라(정지 상태에는 바가 없다) 위 바 높이를 빼지 않는다. */
const READING_BAND_ROOT_MARGIN = "0px 0px -60% 0px";

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
 *   스크롤하면 도로 맨 위가 된다. 되돌린 뒤에야 지금 문단을 재기 시작한다(그 전의 0번 문단을 저장하지 않게).
 * - **지금 문단**: 화면 위쪽 띠에 걸린 문단 중 가장 앞 문단. 마지막 문단이 화면에 들어오면 다 읽음이다.
 * - **저장**: 자리가 바뀌면 3초 뒤 저장한다(스크롤하는 동안 요청이 쏟아지지 않게). 페이지가 숨거나(탭 전환·앱
 *   전환·닫기) 이 화를 떠날 때(다른 화로 옮김 포함) 기다리던 저장을 `keepalive` 로 바로 보낸다 — 그때는 보통 요청이
 *   끊긴다.
 * - **떠날 때**: 저장 응답에 본문이 없어 상세 캐시의 이어 읽기·읽음 표시가 낡는다 — 마지막 저장을 보낸 뒤 상세를
 *   다시 받게 표시해 작품 정보 화면이 돌아왔을 때 맞는 표시를 보게 한다.
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

  useEffect(() => {
    const container = containerRef.current;
    // 문단이 없는 화는 서버가 자리를 받지 않는다(문단 번호는 문단 수보다 작아야 한다).
    if (container === null || paragraphCount === 0) return;

    let currentIndex: number | undefined;
    let isFinished = wasFinished;
    const visible = new Set<number>();
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
        if (pending !== undefined) void saveReadingPosition(novelId, chapterId, pending);
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
            if (entry.isIntersecting) visible.add(index);
            else visible.delete(index);
          }
          // 띠가 문단 사이 틈에 걸려 아무 문단도 없으면 직전 문단을 그대로 둔다.
          if (visible.size === 0) return;
          currentIndex = Math.min(...visible);
          record();
        },
        { rootMargin: READING_BAND_ROOT_MARGIN },
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
      if (restoredIndex > 0) {
        container.querySelector(`[data-paragraph-index="${restoredIndex}"]`)?.scrollIntoView({ block: "start" });
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
      void flushKeepalive().then(() => queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) }));
    };
    // 화·개정이 바뀌면 읽기 화면이 새로 마운트된다(호출부가 화 id 로 key 를 준다). 저장된 자리는 열 때 한 번만 쓴다.
  }, []);
}
