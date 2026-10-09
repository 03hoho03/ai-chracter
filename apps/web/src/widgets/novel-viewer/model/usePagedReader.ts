import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { isFinishedScreen, toAnchorParagraphIndex, toRestoreScreen, type PageAnchor } from "../lib/pageAnchor";
import { toSettleDurationMs } from "../lib/pageGesture";
import {
  clampScreen,
  toNearestScreen,
  toPageGeometry,
  toScreenCount,
  toScrollLeft,
  type PageGeometry,
} from "../lib/pageLayout";
import { easeOut, PAGE_TURN_MS } from "../lib/pageTransition";
import { toTrackingStart, type RestoreOutcome } from "../lib/readingBand";
import type { ReadingPositionSession } from "./useReadingPosition";

/** 되돌린 자리가 반영됐는지 다시 보는 프레임 수(약 0.5초) — 스크롤 모드와 같은 값. */
const MAX_RESTORE_FRAMES = 30;
/** `scrollend` 가 없는 브라우저에서 브라우저가 옮긴 스크롤이 멈췄다고 볼 조용한 간격. */
const SCROLL_SETTLE_FALLBACK_MS = 100;

/** 한 번 잰 쪽 배치. 창 크기·보기 설정·글꼴이 바뀌면 통째로 다시 잰다. */
type PagedLayout = {
  geometry: PageGeometry;
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
  /** 지금 화면(0부터). */
  screen: number;
  /** 화 끝 화면을 포함한 화면 수. 아직 재지 못했으면 0 이다. */
  screenCount: number;
};

/** 쪽 상자가 놓인 자리(뷰포트 기준 px). 넘김 버튼을 그 옆에 붙인다. */
export type PageFrame = { left: number; top: number; width: number; height: number };

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
  isFinePointer: boolean;
  /** 보기 설정(글자 크기·줄 간격)에서 나온 조판 클래스. 바뀌면 쪽을 다시 잰다. */
  typographyClassName: string;
};

/**
 * 페이지 모드 본문의 쪽 나누기와 읽은 자리. 본문은 다단 블록 하나로 흐르고, 한 화면 폭의 스크롤러를 `scrollLeft` 로
 * 옮겨 넘긴다 — 브라우저가 줄 나눔을 그대로 하므로 쪽에 걸친 문단도 한 문단으로 조판되고 보조기기·찾기가 그대로 읽는다.
 *
 * - **재기**: 창 크기와 보기 설정에서 쪽 기하(`toPageGeometry`)를 구해 놓은 뒤, 화 끝 블록이 끝나는 단으로 화면 수를
 *   세고 다단 요소 폭을 `화면 수 × 한 화면 폭` 으로 다시 놓는다 — 그러지 않으면 브라우저가 다단 요소의 끝 쪽 안쪽
 *   여백을 스크롤 영역에 넣지 않아 마지막 화면에 닿지 못한다. 펼침에서 화 끝 블록이 오른쪽 단에 떨어지면 빈 단 하나를
 *   켜서 새 펼침의 왼쪽으로 민다(CSS 의 쪽 나눔 값은 다단에서 단 하나만 넘긴다).
 * - **다시 재기**: 본문 상자 크기 변화, 보기 설정 변경, 글꼴 도착 때. 글꼴이 도착하면 상자 크기는 그대로여도 쪽 폭
 *   상한(`max-w-prose`, 글자 폭 단위)과 줄 나눔이 바뀐다. 다시 잰 뒤에는 읽던 자리(앵커)가 든 화면으로 돌아가기만
 *   하고 앵커를 다시 정하지 않는다 — 연달아 바뀌어도 자리가 미끄러지지 않게.
 * - **앵커**: 문단, 문단 안 글자 위치, 화 끝 화면 표시. 사용자가 화면을 옮길 때만 그 화면으로 다시 정하고
 *   (`toAnchorParagraphIndex`), 그때만 문단을 `session` 에 알린다. 서버에는 문단 번호만 가지만, 긴 문단 하나가 덮은
 *   화면과 화 끝 화면은 문단 번호만으로는 다시 잰 뒤 한 화면 앞으로 되돌아가 글자 위치와 화 끝 표시를 함께 든다.
 * - **되돌리기**: 라우터가 이동을 끝낸 뒤, 본문을 그린 다음에 읽은 `document.fonts.ready` 를 기다려 잰다(먼저 읽어
 *   두면 본문 글꼴 조각을 기다리지 않고 풀린다). 재기 시작은 스크롤 모드와 같은 분류(`toTrackingStart`)를 따른다.
 * - **다 읽음**: 마지막 문단이 시작하는 화면에 왔거나 지나왔다(`isFinishedScreen`).
 * - **브라우저가 옮긴 스크롤**: 포커스 이동·보조기기·찾기가 스크롤러를 화면 사이에 놓으면, 멈춘 뒤 화면에 맞추고
 *   사용자 이동으로 친다. 넘김 전환과 끌기 중의 스크롤은 우리가 움직인 것이라 건드리지 않는다.
 */
export function usePagedReader({ session, paragraphCount, isFinePointer, typographyClassName }: UsePagedReaderOptions) {
  const viewportRef = useRef<HTMLElement>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const columnsRef = useRef<HTMLDivElement>(null);
  const spacerRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const probeRef = useRef<HTMLDivElement>(null);
  const safeAreaProbeRef = useRef<HTMLDivElement>(null);

  const layoutRef = useRef<PagedLayout | undefined>(undefined);
  const screenRef = useRef(0);
  const anchorRef = useRef<PageAnchor | undefined>(undefined);
  // 되돌리는 중 → (되돌리기를 못 했거나 자리를 몰라) 첫 사용자 이동을 기다림 → 재는 중.
  const trackingRef = useRef<"restoring" | "waiting" | "tracking">("restoring");
  const animationRef = useRef<{ frame: number; to: number } | undefined>(undefined);
  const isFinePointerRef = useRef(isFinePointer);
  const isDirectMoveRef = useRef(false);
  const directMoveStartRef = useRef(0);
  const isRelayoutPendingRef = useRef(false);
  const [position, setPosition] = useState<PagedPosition>({ screen: 0, screenCount: 0 });
  const [frame, setFrame] = useState<PageFrame | undefined>(undefined);
  const { hasRouteSettled } = session;

  function measure(): PagedLayout | undefined {
    const viewport = viewportRef.current;
    const scroller = scrollerRef.current;
    const columns = columnsRef.current;
    const spacer = spacerRef.current;
    const end = endRef.current;
    const probe = probeRef.current;
    const safeAreaProbe = safeAreaProbeRef.current;
    if (!viewport || !scroller || !columns || !spacer || !end || !probe || !safeAreaProbe) return undefined;

    const probeStyle = getComputedStyle(probe);
    const safeAreaStyle = getComputedStyle(safeAreaProbe);
    const geometry = toPageGeometry({
      width: viewport.clientWidth,
      height: viewport.clientHeight,
      safeArea: {
        left: pxOf(safeAreaStyle.paddingLeft),
        right: pxOf(safeAreaStyle.paddingRight),
        top: pxOf(safeAreaStyle.paddingTop),
        bottom: pxOf(safeAreaStyle.paddingBottom),
      },
      isFinePointer: isFinePointerRef.current,
      pagePaddingPx: pxOf(probeStyle.paddingLeft),
      proseWidthPx: probe.getBoundingClientRect().width,
      lineHeightPx: lineHeightOf(probeStyle),
    });
    const { columnCount, columnWidth, columnGap, step, columnHeight } = geometry;
    if (columnWidth <= 0 || columnHeight <= 0) return undefined;

    // 잰 값이라 클래스로 줄 수 없어 요소 스타일에 직접 쓴다. 렌더는 이 속성들을 건드리지 않는다.
    Object.assign(scroller.style, {
      left: `${geometry.left}px`,
      top: `${geometry.top}px`,
      width: `${step}px`,
      height: `${columnHeight}px`,
    });
    Object.assign(columns.style, {
      width: `${step}px`,
      height: `${columnHeight}px`,
      columnWidth: `${columnWidth}px`,
      columnGap: `${columnGap}px`,
      columnFill: "auto",
      paddingInline: `${columnGap / 2}px`,
    });
    // 단 높이가 소수일 수 있어 내려 둔다 — 조금이라도 넘치면 화 끝 블록이 빈 단을 하나 더 만든다.
    end.style.minHeight = `${Math.floor(columnHeight)}px`;
    spacer.style.display = "";
    spacer.style.height = `${columnHeight}px`;

    // 단 번호는 다단 요소의 지금 왼쪽(넘긴 만큼 옮겨 간)에서 센다. 단 사이 틈에 든 점은 앞 단으로 친다.
    const columnOf = (x: number): number => {
      const contentLeft = columns.getBoundingClientRect().left + columnGap / 2;
      return Math.floor((x - contentLeft + 0.01) / (columnWidth + columnGap));
    };
    const screenOfRect = (rect: DOMRect): number => Math.floor(columnOf(rect.left) / columnCount);

    const endStart = firstRectOf(end);
    if (columnCount === 2 && endStart !== undefined && columnOf(endStart.left) % 2 === 1) spacer.style.display = "block";
    const endRects = Array.from(end.getClientRects());
    if (endRects.length === 0) return undefined;
    const lastColumnIndex = Math.max(...endRects.map((rect) => columnOf(rect.right - 1)));
    const screenCount = toScreenCount({ lastColumnIndex, columnCount });
    columns.style.width = `${screenCount * step}px`;

    const paragraphs = Array.from(columns.querySelectorAll<HTMLElement>("[data-paragraph-index]"));
    const screenOfOffset = (paragraphIndex: number, offset: number): number | undefined => {
      const paragraph = paragraphs[paragraphIndex];
      if (paragraph === undefined) return undefined;
      const rect = caretRectOf(paragraph, offset);
      return rect === undefined ? undefined : screenOfRect(rect);
    };
    const startScreens = paragraphs.map((_, index) => screenOfOffset(index, 0) ?? 0);

    return { geometry, screenCount, startScreens, screenOfOffset, screenOfRect };
  }

  function showPosition(screen: number, screenCount: number) {
    setPosition((current) =>
      current.screen === screen && current.screenCount === screenCount ? current : { screen, screenCount },
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
    showPosition(screen, layout.screenCount);
    const to = toScrollLeft(screen, layout.geometry.step);
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
    // 다시 재기에 실패하면(아주 작은 창·극단적 확대) 마지막 자리를 그대로 둔다 — 비우면 거터 넘김 버튼이 사라지면서
    // 그 버튼의 포커스가 `<body>` 로 떨어진다. 그동안 넘김은 잰 배치가 없어 아무것도 하지 않는다.
    if (layout !== undefined) {
      const nextFrame = toFrame(layout.geometry);
      setFrame((current) => (isSameFrame(current, nextFrame) ? current : nextFrame));
    }
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

  // 처음 그릴 때와 보기 설정이 바뀔 때는 칠하기 전에 잰다 — 다단이 걸리기 전 본문이 한 번 비치지 않게.
  useLayoutEffect(() => {
    isFinePointerRef.current = isFinePointer;
    anchorRef.current ??= { paragraphIndex: session.toRestoreTarget().index, charOffset: 0, isAtEnd: false };
    relayout();
  }, [typographyClassName, isFinePointer]);

  // 본문 상자 크기 변화와 글꼴 도착. 한 프레임에 한 번만 다시 잰다.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    let frame: number | undefined;
    function schedule() {
      if (frame === undefined) {
        frame = requestAnimationFrame(() => {
          frame = undefined;
          relayout();
        });
      }
    }
    const observer = new ResizeObserver(schedule);
    observer.observe(viewport);
    document.fonts.addEventListener("loadingdone", schedule);
    return () => {
      observer.disconnect();
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
        const target = toScrollLeft(screenRef.current, layout.geometry.step);
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
      const { step } = layout.geometry;
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
      const maxScrollLeft = toScrollLeft(layout.screenCount - 1, layout.geometry.step);
      scroller.scrollLeft = Math.min(Math.max(directMoveStartRef.current - dx, 0), maxScrollLeft);
    },
    release(direction) {
      if (!isDirectMoveRef.current) return;
      isDirectMoveRef.current = false;
      // 끄는 동안 미룬 다시 재기는 놓은 지금 한다 — 끌던 화면으로 돌아간 뒤 그 화면에서 넘기거나 머문다.
      if (isRelayoutPendingRef.current) relayout();
      const layout = layoutRef.current;
      const scroller = scrollerRef.current;
      if (layout === undefined || !scroller) return;
      const { step } = layout.geometry;
      const target = clampScreen(screenRef.current + direction, layout.screenCount);
      const remainingPx = scroller.scrollLeft - toScrollLeft(target, step);
      moveByUser(target, { durationMs: toSettleDurationMs({ remainingPx, pageWidth: step }) });
    },
  };

  return {
    position,
    frame,
    handle,
    directMove,
    viewportRef,
    scrollerRef,
    columnsRef,
    spacerRef,
    endRef,
    probeRef,
    safeAreaProbeRef,
  };
}

function toFrame({ left, top, step, columnHeight }: PageGeometry): PageFrame {
  return { left, top, width: step, height: columnHeight };
}

function isSameFrame(a: PageFrame | undefined, b: PageFrame | undefined): boolean {
  if (a === undefined || b === undefined) return a === b;
  return a.left === b.left && a.top === b.top && a.width === b.width && a.height === b.height;
}

function pxOf(value: string): number {
  return Number.parseFloat(value) || 0;
}

/** 계산된 줄 높이(px). 브라우저가 `normal` 로 주면 글자 크기의 1.2배로 친다(읽기 설정은 늘 수치를 준다). */
function lineHeightOf(style: CSSStyleDeclaration): number {
  const lineHeight = Number.parseFloat(style.lineHeight);
  return Number.isFinite(lineHeight) ? lineHeight : pxOf(style.fontSize) * 1.2;
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
