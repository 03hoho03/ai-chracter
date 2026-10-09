import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { isFinishedScreen, toAnchorParagraphIndex, toRestoreScreen, type PageAnchor } from "../lib/pageAnchor";
import type { PageFit } from "../lib/pageFit";
import { PAGE_FORMAT_PADDING_PX, PAGE_FORMAT_WIDTH_PX, PAGE_TEXT_HEIGHT_PX, PAGE_TEXT_WIDTH_PX } from "../lib/pageFormat";
import { toSettleDurationMs } from "../lib/pageGesture";
import {
  clampScreen,
  toNearestScreen,
  toPageLabel,
  toScreenCount,
  toScrollLeft,
  type ColumnSpan,
} from "../lib/pageLayout";
import { easeOut, PAGE_TURN_MS } from "../lib/pageTransition";
import { toTrackingStart, type RestoreOutcome } from "../lib/readingBand";
import type { ReadingPositionSession } from "./useReadingPosition";

/** 되돌린 자리가 반영됐는지 다시 보는 프레임 수(약 0.5초) — 스크롤 모드와 같은 값. */
const MAX_RESTORE_FRAMES = 30;
/** `scrollend` 가 없는 브라우저에서 브라우저가 옮긴 스크롤이 멈췄다고 볼 조용한 간격. */
const SCROLL_SETTLE_FALLBACK_MS = 100;

/** 한 번 잰 쪽 배치. 한 장·펼침이 바뀌거나 보기 설정·글꼴이 바뀌면 통째로 다시 잰다(배율만 바뀌면 다시 재지 않는다
 * — 판형 안 조판은 배율과 무관하다). */
type PagedLayout = {
  columnCount: 1 | 2;
  /** 한 화면 폭 = 한 번 넘길 때 움직이는 `scrollLeft`(판형 px). */
  step: number;
  /** 화 끝 블록이 끝나는 단과 펼침의 빈 단 — 논리 쪽 표시를 이것으로 센다. */
  span: ColumnSpan;
  /** 화 끝 화면을 포함한 화면 수. */
  screenCount: number;
  /** 문단마다 시작하는 화면. */
  startScreens: number[];
  /** 문단 안 글자 위치가 든 화면. 재지 못하면 비운다. */
  screenOfOffset: (paragraphIndex: number, offset: number) => number | undefined;
  /** 화면 좌표의 사각형이 든 화면. */
  screenOfRect: (rect: DOMRect) => number;
};

export type PagedPosition = {
  /** 지금 화면(0부터). 펼침이면 두 쪽이 한 화면이다. */
  screen: number;
  /** 화 끝 화면을 포함한 화면 수. 아직 재지 못했으면 0 이다. */
  screenCount: number;
  /** 지금 화면의 논리 쪽 표시("3–4 / 16쪽"). 본문 글꼴이 도착하기 전에는 없다 — 대체 글꼴로 잰 쪽 수는 도착 뒤와
   * 다를 수 있어, 기기와 무관하게 같아야 하는 숫자를 그때는 보이지 않는다. */
  pageLabel: string | undefined;
};

/** 손가락·마우스를 따라 쪽을 움직이는 끌기. */
export type PagedDirectMove = {
  /** 끌기를 시작한다. 쪽을 아직 재지 못했으면 거짓이고 끌지 않는다. */
  begin: () => boolean;
  /** 누른 자리에서 가로로 `dx` 만큼 움직였다(오른쪽이 +). 첫 화면 앞·화 끝 화면 뒤로는 끌려가지 않는다. */
  follow: (dx: number) => void;
  /** 놓았다 — 다음(+1)·이전(-1) 화면으로 넘기거나(0) 지금 화면으로 돌아간다. */
  release: (direction: -1 | 0 | 1) => void;
};

/** 넘김 입력(버튼·탭·손짓·휠·키·쪽 이동 슬라이더)이 부르는 이동. 셋 다 사용자 이동이라 읽은 자리를 옮긴다. */
export type PagedReaderHandle = {
  /** 그 화면으로 바로 옮긴다(위치 표시라 전환 없음). */
  goTo: (screen: number) => void;
  /** 다음·이전 화면으로 넘긴다(움직임 줄이기 설정이 아니면 가로 전환). 화 끝·첫 화면에서는 멈춘다. */
  next: () => void;
  previous: () => void;
};

type UsePagedReaderOptions = {
  session: ReadingPositionSession;
  paragraphCount: number;
  /** 창에 판형을 맞춘 배치. 한 장·펼침이 바뀌면 다시 재고, 배율이 바뀌면 좌표 환산에만 쓴다. */
  fit: PageFit;
  /** 판형 안 조판값(글자 크기·줄 간격)을 나타내는 값. 바뀌면 쪽을 다시 잰다. */
  typographyKey: string;
};

/**
 * 페이지 모드 본문의 쪽 나누기와 읽은 자리. 본문은 고정 판형(논리 360×540px) 크기의 다단 블록 하나로 흐르고, 한 화면
 * 폭의 스크롤러를 `scrollLeft` 로 옮겨 넘긴다 — 브라우저가 줄 나눔을 그대로 하므로 쪽에 걸친 문단도 한 문단으로
 * 조판되고 보조기기·찾기가 그대로 읽는다. 스크롤러는 판형 크기 그대로 조판하고 `transform: scale` 로만 화면에 맞춘다
 * — `zoom` 은 배율마다 다시 조판해 쪽 수가 바뀌고, `transform` 은 바뀌지 않는다(엔진 둘 다 실측).
 *
 * - **재기**: 다단 요소를 판형 크기로 놓은 뒤, 화 끝 블록이 끝나는 단으로 화면 수를 세고 다단 요소 폭을 `화면 수 ×
 *   한 화면 폭` 으로 다시 놓는다 — 그러지 않으면 브라우저가 다단 요소의 끝 쪽 안쪽 여백을 스크롤 영역에 넣지 않아
 *   마지막 화면에 닿지 못한다. 펼침에서 화 끝 블록이 오른쪽 단에 떨어지면 빈 단 하나를 켜서 새 펼침의 왼쪽으로
 *   민다(CSS 의 쪽 나눔 값은 다단에서 단 하나만 넘긴다). 재기 직전, 빈 단을 켠 직후, 폭을 넓힌 직후마다 다단 요소를
 *   처음부터 다시 배치시키고, 쪽 수는 마지막 배치(화면에 그려지는 배치)에서 다시 센다 — WebKit 은 다단을 고쳐 흘릴 때
 *   결과가 직전 배치에 따라 달라져, 같은 판형·같은 설정인데 쪽 수가 바뀌거나 잰 쪽과 그려진 쪽이 어긋난다.
 * - **좌표**: 포인터·사각형은 화면 px 이고 `scrollLeft`·단 폭은 판형 px 다. 화면 거리를 배율로 나눠 판형 px 로 바꾸고,
 *   배율은 계산한 값을 반올림하지 않고 쓴다(반올림하면 단 경계 근처 글자가 앞 단으로 잘못 분류된다).
 * - **다시 재기**: 한 장·펼침 변경, 보기 설정 변경, 글꼴 도착 때. 배율·위치만 바뀌면 다시 재지 않는다. 다시 잰
 *   뒤에는 읽던 자리(앵커)가 든 화면으로 돌아가기만 하고 앵커를 다시 정하지 않는다 — 연달아 바뀌어도 자리가 미끄러지지
 *   않게.
 * - **앵커**: 문단, 문단 안 글자 위치, 화 끝 화면 표시. 사용자가 화면을 옮길 때만 그 화면으로 다시 정하고
 *   (`toAnchorParagraphIndex`), 그때만 문단을 `session` 에 알린다. 서버에는 문단 번호만 가지만, 긴 문단 하나가 덮은
 *   화면과 화 끝 화면은 문단 번호만으로는 다시 잰 뒤 한 화면 앞으로 되돌아가 글자 위치와 화 끝 표시를 함께 든다.
 * - **되돌리기**: 라우터가 이동을 끝낸 뒤, 본문을 그린 다음에 읽은 `document.fonts.ready` 를 기다려 잰다(먼저 읽어
 *   두면 본문 글꼴 조각을 기다리지 않고 풀린다). 재기 시작은 스크롤 모드와 같은 분류(`toTrackingStart`)를 따른다.
 * - **다 읽음**: 마지막 문단이 시작하는 화면에 왔거나 지나왔다(`isFinishedScreen`).
 * - **브라우저가 옮긴 스크롤**: 포커스 이동·보조기기·찾기가 스크롤러를 화면 사이에 놓으면, 멈춘 뒤 화면에 맞추고
 *   사용자 이동으로 친다. 넘김 전환과 끌기 중의 스크롤은 우리가 움직인 것이라 건드리지 않는다.
 */
export function usePagedReader({ session, paragraphCount, fit, typographyKey }: UsePagedReaderOptions) {
  const viewportRef = useRef<HTMLElement>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const columnsRef = useRef<HTMLDivElement>(null);
  const spacerRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const layoutRef = useRef<PagedLayout | undefined>(undefined);
  const screenRef = useRef(0);
  const anchorRef = useRef<PageAnchor | undefined>(undefined);
  // 되돌리는 중 → (되돌리기를 못 했거나 자리를 몰라) 첫 사용자 이동을 기다림 → 재는 중.
  const trackingRef = useRef<"restoring" | "waiting" | "tracking">("restoring");
  const animationRef = useRef<{ frame: number; to: number } | undefined>(undefined);
  const fitRef = useRef(fit);
  const isFontReadyRef = useRef(false);
  const isDirectMoveRef = useRef(false);
  const directMoveStartRef = useRef(0);
  const isRelayoutPendingRef = useRef(false);
  const [position, setPosition] = useState<PagedPosition>({ screen: 0, screenCount: 0, pageLabel: undefined });
  const { hasRouteSettled } = session;

  function measure(): PagedLayout | undefined {
    const columns = columnsRef.current;
    const spacer = spacerRef.current;
    const end = endRef.current;
    if (!columns || !spacer || !end) return undefined;

    const { columnCount } = fitRef.current;
    const step = columnCount * PAGE_FORMAT_WIDTH_PX;
    // 판형 상수라 클래스로도 줄 수 있지만, 폭은 잰 뒤 다시 쓰므로 같은 자리(요소 스타일)에 둔다. 렌더는 이 속성들을
    // 건드리지 않는다.
    Object.assign(columns.style, {
      width: `${step}px`,
      height: `${PAGE_TEXT_HEIGHT_PX}px`,
      columnWidth: `${PAGE_TEXT_WIDTH_PX}px`,
      columnGap: `${2 * PAGE_FORMAT_PADDING_PX}px`,
      columnFill: "auto",
      paddingInline: `${PAGE_FORMAT_PADDING_PX}px`,
    });
    end.style.minHeight = `${PAGE_TEXT_HEIGHT_PX}px`;
    spacer.style.display = "";
    spacer.style.height = `${PAGE_TEXT_HEIGHT_PX}px`;
    layOutFromScratch(columns);

    // 단 번호는 다단 요소의 지금 왼쪽(넘긴 만큼 옮겨 간)에서 판형 px 로 센다. 단 사이 틈에 든 점은 앞 단으로 친다.
    // 배율은 지금 값을 읽는다 — 재고 난 뒤 배율만 바뀌어도 이 함수들을 다시 쓴다.
    const columnOf = (x: number): number => {
      const offset = (x - columns.getBoundingClientRect().left) / fitRef.current.scale - PAGE_FORMAT_PADDING_PX;
      return Math.floor((offset + 0.01) / PAGE_FORMAT_WIDTH_PX);
    };
    const screenOfRect = (rect: DOMRect): number => Math.floor(columnOf(rect.left) / columnCount);

    // 지금 놓인 배치에서 화 끝 블록이 끝나는 단과 켜 둔 빈 단을 센다.
    const readSpan = (): ColumnSpan | undefined => {
      const endRects = Array.from(end.getClientRects());
      if (endRects.length === 0) return undefined;
      const endStart = firstRectOf(end);
      return {
        lastColumnIndex: Math.max(...endRects.map((rect) => columnOf(rect.right - 1))),
        spacerColumnIndex:
          spacer.style.display === "block" && endStart !== undefined ? columnOf(endStart.left) - 1 : undefined,
      };
    };

    const endStart = firstRectOf(end);
    if (columnCount === 2 && endStart !== undefined && columnOf(endStart.left) % 2 === 1) {
      spacer.style.display = "block";
      layOutFromScratch(columns);
    }
    let span = readSpan();
    if (span === undefined) return undefined;
    let screenCount = toScreenCount({ lastColumnIndex: span.lastColumnIndex, columnCount });
    // 폭을 넓힌 뒤에도 처음부터 다시 배치하고 다시 센다 — WebKit 은 폭 변경을 고쳐 흘려 잰 배치와 다른 배치를 그린다.
    // 다시 센 화면 수가 넓힌 폭보다 크면 한 번 더 넓힌다(작으면 남는 폭은 넘김이 닿지 않아 그대로 둔다).
    for (let attempt = 0; attempt < 2; attempt += 1) {
      columns.style.width = `${screenCount * step}px`;
      layOutFromScratch(columns);
      const settled = readSpan();
      if (settled === undefined) return undefined;
      const settledCount = toScreenCount({ lastColumnIndex: settled.lastColumnIndex, columnCount });
      const needsWider = settledCount > screenCount;
      span = settled;
      screenCount = settledCount;
      if (!needsWider) break;
    }

    const paragraphs = Array.from(columns.querySelectorAll<HTMLElement>("[data-paragraph-index]"));
    const screenOfOffset = (paragraphIndex: number, offset: number): number | undefined => {
      const paragraph = paragraphs[paragraphIndex];
      if (paragraph === undefined) return undefined;
      const rect = caretRectOf(paragraph, offset);
      return rect === undefined ? undefined : screenOfRect(rect);
    };
    const startScreens = paragraphs.map((_, index) => screenOfOffset(index, 0) ?? 0);

    return {
      columnCount,
      step,
      span,
      screenCount,
      startScreens,
      screenOfOffset,
      screenOfRect,
    };
  }

  function showPosition(layout: PagedLayout, screen: number) {
    const { screenCount } = layout;
    const pageLabel = isFontReadyRef.current
      ? toPageLabel({ ...layout.span, screen, columnCount: layout.columnCount })
      : undefined;
    setPosition((current) =>
      current.screen === screen && current.screenCount === screenCount && current.pageLabel === pageLabel
        ? current
        : { screen, screenCount, pageLabel },
    );
  }

  /** 넘김 전환이 돌고 있으면 목표 자리로 바로 끝낸다. */
  function finishAnimation() {
    const animation = animationRef.current;
    if (animation === undefined) return;
    cancelAnimationFrame(animation.frame);
    animationRef.current = undefined;
    if (scrollerRef.current) scrollerRef.current.scrollLeft = animation.to;
  }

  /** 그 화면으로 옮긴다. `durationMs` 가 0 이거나 움직임 줄이기 설정이면 바로 옮긴다. */
  function moveTo(layout: PagedLayout, screen: number, { durationMs }: { durationMs: number }) {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    finishAnimation();
    screenRef.current = screen;
    showPosition(layout, screen);
    const to = toScrollLeft(screen, layout.step);
    const from = scroller.scrollLeft;
    if (durationMs <= 0 || from === to || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      scroller.scrollLeft = to;
      return;
    }
    const startedAt = performance.now();
    const tick = (now: number) => {
      const progress = (now - startedAt) / durationMs;
      scroller.scrollLeft = from + (to - from) * easeOut(progress);
      if (progress < 1) animationRef.current = { frame: requestAnimationFrame(tick), to };
      else animationRef.current = undefined;
    };
    animationRef.current = { frame: requestAnimationFrame(tick), to };
  }

  /** 다시 재고 앵커가 든 화면으로 돌아간다. 앵커는 바꾸지 않고 읽은 자리도 알리지 않는다. 끄는 중이면 놓을 때까지
   * 미룬다 — 손 밑의 쪽이 다시 잰 화면으로 튀고, 끌기는 옛 화면 폭으로 계속 계산된다. */
  function relayout() {
    if (isDirectMoveRef.current) {
      isRelayoutPendingRef.current = true;
      return;
    }
    isRelayoutPendingRef.current = false;
    finishAnimation();
    const layout = measure();
    layoutRef.current = layout;
    const anchor = anchorRef.current;
    if (layout === undefined || anchor === undefined) return;
    const offsetScreen = anchor.charOffset > 0 ? layout.screenOfOffset(anchor.paragraphIndex, anchor.charOffset) : undefined;
    const screen = toRestoreScreen({ anchor, startScreens: layout.startScreens, endScreen: layout.screenCount - 1, offsetScreen });
    moveTo(layout, screen, { durationMs: 0 });
  }

  function anchorAt(layout: PagedLayout, screen: number): PageAnchor {
    const isAtEnd = screen === layout.screenCount - 1;
    if (layout.startScreens.length === 0) return { paragraphIndex: 0, charOffset: 0, isAtEnd };
    const paragraphIndex = toAnchorParagraphIndex({ startScreens: layout.startScreens, screen });
    const isCovered = !isAtEnd && layout.startScreens[paragraphIndex] !== screen;
    return { paragraphIndex, charOffset: isCovered ? firstOffsetOnScreen(layout, paragraphIndex, screen) : 0, isAtEnd };
  }

  /** 문단 안에서 그 화면에 처음 놓인 글자 위치. 글자 위치가 든 화면은 위치를 따라 줄지 않아 이분법으로 찾는다. */
  function firstOffsetOnScreen(layout: PagedLayout, paragraphIndex: number, screen: number): number {
    const text = columnsRef.current?.querySelectorAll("[data-paragraph-index]")[paragraphIndex]?.firstChild;
    if (!(text instanceof Text)) return 0;
    let low = 0;
    let high = text.length;
    while (low < high) {
      const middle = Math.floor((low + high) / 2);
      if ((layout.screenOfOffset(paragraphIndex, middle) ?? screen) < screen) low = middle + 1;
      else high = middle;
    }
    return low;
  }

  /** 지금 앵커 문단과 다 읽음을 알린다. */
  function reportCurrent() {
    const anchor = anchorRef.current;
    const layout = layoutRef.current;
    if (paragraphCount === 0 || anchor === undefined) return;
    session.reportParagraph(anchor.paragraphIndex);
    const lastParagraphScreen = layout?.startScreens.at(-1);
    if (lastParagraphScreen !== undefined && isFinishedScreen({ screen: screenRef.current, lastParagraphScreen })) {
      session.reportFinished();
    }
  }

  function startTracking() {
    trackingRef.current = "tracking";
    session.reportTrackingStarted();
    reportCurrent();
  }

  /** 사용자가 옮긴 화면. 화면이 바뀌었을 때만 앵커를 다시 정하고 알린다 — 기다리던 중이면 이때부터 잰다. */
  function moveByUser(target: number, { durationMs }: { durationMs: number }) {
    const layout = layoutRef.current;
    if (layout === undefined) return;
    const screen = clampScreen(target, layout.screenCount);
    const isSameScreen = screen === screenRef.current;
    moveTo(layout, screen, { durationMs });
    if (isSameScreen) return;
    anchorRef.current = anchorAt(layout, screen);
    if (trackingRef.current === "tracking") reportCurrent();
    else startTracking();
  }

  // 좌표 환산과 다시 재기가 지금 배치를 읽게 한다. 아래 재기보다 먼저 돈다(같은 커밋의 레이아웃 효과는 선언 순서).
  useLayoutEffect(() => {
    fitRef.current = fit;
  }, [fit]);

  // 처음 그릴 때, 보기 설정이 바뀔 때, 한 장·펼침이 바뀔 때는 칠하기 전에 잰다 — 다단이 걸리기 전 본문이 한 번 비치지
  // 않게.
  useLayoutEffect(() => {
    anchorRef.current ??= { paragraphIndex: session.toRestoreTarget().index, charOffset: 0, isAtEnd: false };
    relayout();
  }, [typographyKey, fit.columnCount]);

  // 본문 글꼴이 처음 다 오면 그때부터 쪽 숫자를 보인다. 본문을 그린 뒤에 읽어야 본문이 쓰는 글꼴 조각까지 기다린다.
  // WebKit 의 `document.fonts.check` 는 조각 하나만 와도 참을 내 판정에 쓰지 않는다.
  useEffect(() => {
    let isCancelled = false;
    void document.fonts.ready.then(() => {
      if (isCancelled) return;
      isFontReadyRef.current = true;
      relayout();
    });
    return () => {
      isCancelled = true;
    };
  }, []);

  // 글꼴 조각이 더 오면(화마다 쓰는 글자가 달라 조각이 늦게 더 온다) 줄 나눔이 바뀌어 다시 잰다. 한 프레임에 한 번만.
  useEffect(() => {
    let frame: number | undefined;
    function schedule() {
      if (frame === undefined) {
        frame = requestAnimationFrame(() => {
          frame = undefined;
          relayout();
        });
      }
    }
    document.fonts.addEventListener("loadingdone", schedule);
    return () => {
      document.fonts.removeEventListener("loadingdone", schedule);
      if (frame !== undefined) cancelAnimationFrame(frame);
    };
  }, []);

  // 되돌리기와 재기 시작. 이 본문이 붙어 있는 동안 한 번 — 화를 열 때는 라우터가 이동을 끝낸 뒤, 같은 화 안에서 넘김
  // 방식을 바꿔 붙을 때는 붙는 순간이다.
  useEffect(() => {
    if (!hasRouteSettled) return;
    let isCancelled = false;
    let frame: number | undefined;
    const { index, basis } = session.toRestoreTarget();

    function finish(outcome: "restored" | "failed") {
      if (trackingRef.current !== "restoring") return;
      // 되돌릴 문단이 맨 위가 아니거나 저장된 자리가 있으면 반영 결과로, 아니면 처음 여는 화·자리를 모르는 화의
      // 분류로 재기 시작을 정한다(스크롤 모드와 같은 분류).
      const restore: RestoreOutcome = index > 0 || basis === "saved" ? outcome : basis;
      if (toTrackingStart(restore) === "now") startTracking();
      else trackingRef.current = "waiting";
    }

    function confirm(attempt: number) {
      frame = requestAnimationFrame(() => {
        frame = undefined;
        if (trackingRef.current !== "restoring") return;
        // 끄는 동안에는 되돌린 자리로 다시 놓지 않는다(손 밑의 쪽과 싸운다) — 놓은 뒤에 이어서 확인한다.
        if (isDirectMoveRef.current) {
          confirm(attempt);
          return;
        }
        const layout = layoutRef.current;
        const scroller = scrollerRef.current;
        if (layout === undefined || !scroller) {
          finish("failed");
          return;
        }
        const target = toScrollLeft(screenRef.current, layout.step);
        const isRestored = Math.abs(scroller.scrollLeft - target) <= 1;
        if (isRestored || attempt + 1 >= MAX_RESTORE_FRAMES) {
          finish(isRestored ? "restored" : "failed");
          return;
        }
        scroller.scrollLeft = target;
        confirm(attempt + 1);
      });
    }

    // 본문을 그린 뒤에 읽어야 본문이 쓰는 글꼴 조각까지 기다린다.
    void document.fonts.ready.then(() => {
      if (isCancelled || trackingRef.current !== "restoring") return;
      relayout();
      confirm(0);
    });
    return () => {
      isCancelled = true;
      if (frame !== undefined) cancelAnimationFrame(frame);
    };
  }, [hasRouteSettled]);

  // 포커스 이동·보조기기·찾기처럼 브라우저가 옮긴 스크롤을 멈춘 뒤 화면에 맞춘다.
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const supportsScrollEnd = "onscrollend" in window;
    let timer: ReturnType<typeof setTimeout> | undefined;

    function align() {
      timer = undefined;
      const layout = layoutRef.current;
      if (animationRef.current !== undefined || isDirectMoveRef.current || layout === undefined || !scroller) return;
      const { step } = layout;
      if (Math.abs(scroller.scrollLeft - toScrollLeft(screenRef.current, step)) <= 1) return;
      // 포커스가 옮겨 간 요소가 보이면 그 요소의 화면으로 — 가장 가까운 화면이 그 요소를 다시 가릴 수 있다.
      const focused = visibleFocusedRect(scroller);
      const screen =
        focused === undefined
          ? toNearestScreen({ scrollLeft: scroller.scrollLeft, step, screenCount: layout.screenCount })
          : layout.screenOfRect(focused);
      moveByUser(screen, { durationMs: 0 });
    }

    function handleScroll() {
      if (supportsScrollEnd) return;
      if (timer !== undefined) clearTimeout(timer);
      timer = setTimeout(align, SCROLL_SETTLE_FALLBACK_MS);
    }

    scroller.addEventListener("scroll", handleScroll, { passive: true });
    if (supportsScrollEnd) scroller.addEventListener("scrollend", align);
    return () => {
      scroller.removeEventListener("scroll", handleScroll);
      scroller.removeEventListener("scrollend", align);
      if (timer !== undefined) clearTimeout(timer);
    };
  }, []);

  // 떠날 때 돌던 전환을 멈춘다.
  useEffect(() => () => finishAnimation(), []);

  const handle: PagedReaderHandle = {
    goTo: (screen) => moveByUser(screen, { durationMs: 0 }),
    next: () => moveByUser(screenRef.current + 1, { durationMs: PAGE_TURN_MS }),
    previous: () => moveByUser(screenRef.current - 1, { durationMs: PAGE_TURN_MS }),
  };

  // 끄는 동안은 손을 그대로 따라가는 직접 조작이라 움직임 줄이기 설정과 무관하게 따라간다. 놓은 뒤 맞춰 들어가는
  // 이동은 전환이라 남은 거리에 비례한 시간으로 움직이고, 움직임 줄이기 설정이면 바로 맞춘다.
  const directMove: PagedDirectMove = {
    begin() {
      const scroller = scrollerRef.current;
      if (layoutRef.current === undefined || !scroller) return false;
      finishAnimation();
      isDirectMoveRef.current = true;
      directMoveStartRef.current = scroller.scrollLeft;
      return true;
    },
    follow(dx) {
      const layout = layoutRef.current;
      const scroller = scrollerRef.current;
      if (!isDirectMoveRef.current || layout === undefined || !scroller) return;
      const maxScrollLeft = toScrollLeft(layout.screenCount - 1, layout.step);
      // 손은 화면 px 로 움직이고 `scrollLeft` 는 판형 px 라 배율로 나눈다 — 그래야 쪽이 손가락 밑에 붙어 따라온다.
      const logicalDx = dx / fitRef.current.scale;
      scroller.scrollLeft = Math.min(Math.max(directMoveStartRef.current - logicalDx, 0), maxScrollLeft);
    },
    release(direction) {
      if (!isDirectMoveRef.current) return;
      isDirectMoveRef.current = false;
      // 끄는 동안 미룬 다시 재기는 놓은 지금 한다 — 끌던 화면으로 돌아간 뒤 그 화면에서 넘기거나 머문다.
      if (isRelayoutPendingRef.current) relayout();
      const layout = layoutRef.current;
      const scroller = scrollerRef.current;
      if (layout === undefined || !scroller) return;
      const { step } = layout;
      const target = clampScreen(screenRef.current + direction, layout.screenCount);
      const remainingPx = scroller.scrollLeft - toScrollLeft(target, step);
      moveByUser(target, { durationMs: toSettleDurationMs({ remainingPx, pageWidth: step }) });
    },
  };

  return {
    position,
    handle,
    directMove,
    viewportRef,
    scrollerRef,
    columnsRef,
    spacerRef,
    endRef,
  };
}

/** 다단 요소를 처음부터 다시 배치시킨다(`display: none` 왕복). WebKit 은 이미 배치된 다단을 고쳐 흘리면(빈 단을
 * 켰다 끄거나, 글자 크기를 바꿨다 되돌리거나, 폭을 바꾸면) 처음 배치와 다른 쪽 나눔을 낸다. 스크롤 위치가 0 으로 돌아가지만 재기 뒤
 * 곧바로 앵커 화면으로 다시 옮기고, 한 작업 안에서 끝나 그 사이가 칠해지지 않는다. 숨는 순간 브라우저가 안의 포커스를
 * 놓을 수 있어(화 끝 링크에 포커스가 있는 채 글꼴 조각이 도착하는 경우) 놓았으면 제자리로 돌려준다. */
function layOutFromScratch(element: HTMLElement) {
  const focused = document.activeElement;
  element.style.display = "none";
  void element.offsetHeight;
  element.style.display = "";
  if (focused instanceof HTMLElement && focused !== document.activeElement && element.contains(focused)) {
    focused.focus({ preventScroll: true });
  }
}

function firstRectOf(element: Element): DOMRect | undefined {
  return Array.from(element.getClientRects()).find((rect) => rect.height > 0);
}

/** 문단 안 글자 위치의 사각형. 접힌 범위는 폭이 늘 0 이라 높이로 거르고(앞 개행이 높이 0 사각형을 낸다), 글자가
 * 없는 문단은 문단 요소의 사각형을 쓴다. */
function caretRectOf(paragraph: HTMLElement, offset: number): DOMRect | undefined {
  const text = paragraph.firstChild;
  if (text instanceof Text && text.length > 0) {
    const range = document.createRange();
    range.setStart(text, Math.min(offset, text.length));
    range.collapse(true);
    const rect = Array.from(range.getClientRects()).find((candidate) => candidate.height > 0);
    if (rect !== undefined) return rect;
  }
  return firstRectOf(paragraph);
}

/** 스크롤러 안에서 포커스를 가진 요소가 지금 스크롤러에 보이면 그 사각형. */
function visibleFocusedRect(scroller: HTMLElement): DOMRect | undefined {
  const active = document.activeElement;
  if (!(active instanceof HTMLElement) || active === scroller || !scroller.contains(active)) return undefined;
  const rect = firstRectOf(active);
  if (rect === undefined) return undefined;
  const bounds = scroller.getBoundingClientRect();
  return rect.right > bounds.left && rect.left < bounds.right ? rect : undefined;
}
