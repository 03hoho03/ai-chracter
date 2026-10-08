import { useEffect, useLayoutEffect, useRef, type DragEvent, type MouseEvent, type PointerEvent, type RefObject } from "react";

import { toPageGesture } from "../lib/pageGesture";
import { toPageKeyAction, type PageKeyFocus } from "../lib/pageKey";
import { reduceWheel, type WheelTurnState } from "../lib/wheelTurn";
import { INTERACTIVE_SELECTOR } from "./useChromeVisibility";
import type { PagedDirectMove, PagedReaderHandle } from "./usePagedReader";

/** 가로로 이만큼 움직여야 끌기로 친다 — 탭으로 치는 거리와 같은 값이라, 탭이 아닌 가로 손짓은 곧바로 쪽을 끈다. */
const DRAG_START_PX = 10;
/** 손을 뗄 때의 속도를 이 시간 안의 움직임으로 잰다. 더 길면 멈췄다 놓은 손짓도 빠르게 튕긴 것으로 읽힌다. */
const VELOCITY_WINDOW_MS = 100;
/** iOS 의 화면 가장자리 뒤로 가기 손짓이 시작되는 폭. */
const EDGE_GUARD_PX = 20;

type PointerSample = { x: number; time: number };

type PointerStart = {
  pointerId: number;
  pointerType: string;
  x: number;
  y: number;
  time: number;
  isOnInteractive: boolean;
};

type UsePageInputOptions = {
  /** 손짓·휠을 받는 본문 상자. */
  viewportRef: RefObject<HTMLElement | null>;
  handle: PagedReaderHandle;
  directMove: PagedDirectMove;
  /** 한 화면 폭(px). 아직 재지 못했으면 0 이고, 그동안의 손짓은 넘기지 않는다. */
  pageWidth: number;
  screenCount: number;
  isSettingsOpen: boolean;
  settingsPanelRef: RefObject<HTMLElement | null>;
  /** 본문 가운데 탭 — 보기 설정이 열려 있으면 그것만 닫고, 아니면 바를 여닫는다. */
  onBodyTap: () => void;
};

/**
 * 페이지 모드의 넘김 입력. 탭·스와이프·마우스 끌기는 포인터 흐름 하나가 받아 한 번의 누름-뗌을 동작 하나로 가른다
 * (`toPageGesture` — 탭을 먼저 본다). 탭과 넘김을 따로 듣는 처리기 둘을 두면 같은 뗌에 바 토글과 넘김이 함께 불린다.
 *
 * - **끌기**: 가로로 탭 거리 이상 움직이면 쪽이 손을 그대로 따라오고, 놓으면 넘기거나 제자리로 맞춰 들어간다. 끌고
 *   놓은 직후의 click 은 한 번 막는다 — 링크 위에서 시작한 끌기가 작가의 말·다음 화로 새지 않게. 막을 표시는 누를
 *   때마다 지운다(끌고 뗀 자리가 다른 요소면 click 이 오지 않아, 그대로 두면 다음 정상 클릭을 삼킨다).
 * - **확대**: 핀치로 확대한 동안의 손짓은 확대한 화면을 둘러보는 것이라 넘기지 않는다(가운데 탭의 바 토글은 둔다).
 * - **휠**: 한 번 굴리거나 밀면 한 쪽(`reduceWheel`). 확대 단축(Ctrl+휠·트랙패드 핀치)은 브라우저에 맡기고, 그 밖의
 *   휠은 기본 동작을 막는다 — 트랙패드 가로 밀기가 브라우저의 뒤로 가기 손짓으로 새지 않게.
 * - **키**: 창에서 버블 단계로 듣고(다른 처리기가 이미 쓴 키는 건너뛴다), 포커스 자리를 가려 `toPageKeyAction` 에
 *   맡긴다. `Esc` 는 셸이 따로 맡는다.
 * - **화면 가장자리**: iOS 의 가장자리 스와이프(뒤로 가기)가 쪽 넘김과 부딪혀, 가장자리에서 시작한 터치의 기본 동작을
 *   막아 본다. 웹에서는 확실히 막을 수 없어 실기기에서 확인할 일이다. 가장자리는 쪽 바깥 여백이라 막아도 눌릴 링크가
 *   없다.
 */
export function usePageInput(options: UsePageInputOptions) {
  const { viewportRef, handle, directMove, pageWidth, isSettingsOpen, onBodyTap } = options;
  const optionsRef = useRef(options);
  const startRef = useRef<PointerStart | undefined>(undefined);
  const samplesRef = useRef<PointerSample[]>([]);
  const isDraggingRef = useRef(false);
  const suppressClickRef = useRef(false);
  const wheelStateRef = useRef<WheelTurnState>({});

  // 창·본문에 직접 단 처리기는 처음 한 번 달아 두므로 지금 값을 이 ref 로 읽는다.
  useLayoutEffect(() => {
    optionsRef.current = options;
  });

  function setDragging(isDragging: boolean) {
    isDraggingRef.current = isDragging;
    viewportRef.current?.toggleAttribute("data-dragging", isDragging);
  }

  function handlePointerDown(event: PointerEvent<HTMLElement>) {
    suppressClickRef.current = false;
    if (!event.isPrimary || event.button !== 0) {
      startRef.current = undefined;
      return;
    }
    const target = event.target;
    startRef.current = {
      pointerId: event.pointerId,
      pointerType: event.pointerType,
      x: event.clientX,
      y: event.clientY,
      time: event.timeStamp,
      isOnInteractive: target instanceof Element && target.closest(INTERACTIVE_SELECTOR) !== null,
    };
    samplesRef.current = [{ x: event.clientX, time: event.timeStamp }];
  }

  function handlePointerMove(event: PointerEvent<HTMLElement>) {
    const start = startRef.current;
    if (start === undefined || event.pointerId !== start.pointerId) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    const samples = samplesRef.current;
    samples.push({ x: event.clientX, time: event.timeStamp });
    while (samples.length > 2 && event.timeStamp - (samples[0]?.time ?? event.timeStamp) > VELOCITY_WINDOW_MS) samples.shift();

    if (!isDraggingRef.current) {
      const isHorizontalDrag = Math.abs(dx) >= DRAG_START_PX && Math.abs(dx) >= Math.abs(dy);
      if (!isHorizontalDrag || isZoomed() || !directMove.begin()) return;
      setDragging(true);
      // 마우스는 본문 밖으로 끌고 나가도 계속 따라오게 잡아 둔다(터치는 누른 요소에 저절로 묶인다).
      if (start.pointerType === "mouse") event.currentTarget.setPointerCapture(event.pointerId);
    }
    directMove.follow(dx);
  }

  function handlePointerUp(event: PointerEvent<HTMLElement>) {
    const start = startRef.current;
    startRef.current = undefined;
    const wasDragging = isDraggingRef.current;
    setDragging(false);
    if (start === undefined || event.pointerId !== start.pointerId) return;

    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    if (Math.hypot(dx, dy) >= DRAG_START_PX) suppressClickRef.current = true;
    const gesture = toPageGesture({
      dx,
      dy,
      dt: event.timeStamp - start.time,
      velocityX: releaseVelocity(samplesRef.current, { x: event.clientX, time: event.timeStamp }),
      clientX: event.clientX,
      viewportWidth: window.innerWidth,
      pageWidth,
      targetIsInteractive: start.isOnInteractive,
      isSettingsOpen,
      isZoomed: isZoomed(),
    });

    if (gesture === "close-settings" || gesture === "toggle-chrome") onBodyTap();
    else if (gesture === "previous") turn(wasDragging, -1);
    else if (gesture === "next") turn(wasDragging, 1);
    else if (wasDragging) directMove.release(0);
  }

  function turn(wasDragging: boolean, direction: -1 | 1) {
    if (wasDragging) directMove.release(direction);
    else if (direction === 1) handle.next();
    else handle.previous();
  }

  function handlePointerCancel(event: PointerEvent<HTMLElement>) {
    if (startRef.current?.pointerId !== event.pointerId) return;
    startRef.current = undefined;
    if (isDraggingRef.current) directMove.release(0);
    setDragging(false);
  }

  function handleClickCapture(event: MouseEvent<HTMLElement>) {
    if (!suppressClickRef.current) return;
    suppressClickRef.current = false;
    event.preventDefault();
    event.stopPropagation();
  }

  // 링크·이미지를 끌면 브라우저의 끌어 놓기가 시작돼 포인터 흐름을 가로챈다.
  function handleDragStart(event: DragEvent<HTMLElement>) {
    event.preventDefault();
  }

  // 휠과 화면 가장자리 터치. 둘 다 기본 동작을 막아야 해서 수동적이지 않은 처리기로 직접 단다.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    function handleWheel(event: WheelEvent) {
      if (event.ctrlKey || isZoomed()) return;
      event.preventDefault();
      if (isDraggingRef.current) return;
      const { state, turn: wheelTurn } = reduceWheel(wheelStateRef.current, event);
      wheelStateRef.current = state;
      if (wheelTurn === 1) optionsRef.current.handle.next();
      else if (wheelTurn === -1) optionsRef.current.handle.previous();
    }

    function handleTouchStart(event: TouchEvent) {
      const touch = event.touches.item(0);
      if (event.touches.length !== 1 || touch === null) return;
      if (touch.clientX < EDGE_GUARD_PX || touch.clientX > window.innerWidth - EDGE_GUARD_PX) event.preventDefault();
    }

    viewport.addEventListener("wheel", handleWheel, { passive: false });
    viewport.addEventListener("touchstart", handleTouchStart, { passive: false });
    return () => {
      viewport.removeEventListener("wheel", handleWheel);
      viewport.removeEventListener("touchstart", handleTouchStart);
    };
  }, []);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented) return;
      const current = optionsRef.current;
      const action = toPageKeyAction({
        key: event.key,
        shiftKey: event.shiftKey,
        hasModifier: event.ctrlKey || event.metaKey || event.altKey,
        focus: toFocusKind(document.activeElement, current.settingsPanelRef.current),
      });
      if (action === undefined) return;
      event.preventDefault();
      if (action === "next") current.handle.next();
      else if (action === "previous") current.handle.previous();
      else current.handle.goTo(action === "first" ? 0 : current.screenCount - 1);
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return {
    onPointerDown: handlePointerDown,
    onPointerMove: handlePointerMove,
    onPointerUp: handlePointerUp,
    onPointerCancel: handlePointerCancel,
    onClickCapture: handleClickCapture,
    onDragStart: handleDragStart,
  };
}

function isZoomed(): boolean {
  return (window.visualViewport?.scale ?? 1) > 1;
}

/** 놓기 직전 짧은 구간의 가로 속도(px/ms, 오른쪽이 +). */
function releaseVelocity(samples: readonly PointerSample[], last: PointerSample): number {
  const first = samples.find((sample) => last.time - sample.time <= VELOCITY_WINDOW_MS);
  if (first === undefined || last.time <= first.time) return 0;
  return (last.x - first.x) / (last.time - first.time);
}

/** 키를 누른 순간 포커스가 있는 자리. 슬라이더를 입력칸보다 먼저 본다 — 범위 입력도 `input` 이다. */
function toFocusKind(active: Element | null, settingsPanel: HTMLElement | null): PageKeyFocus {
  if (!(active instanceof HTMLElement)) return "none";
  if (active.closest("[role='slider'], input[type='range']") !== null) return "slider";
  if (active.matches("input, textarea, select") || active.isContentEditable) return "text";
  if (settingsPanel?.contains(active) === true || active.closest("[role='dialog']") !== null) return "panel";
  if (active.closest("a[href], button, summary, [role='button']") !== null) return "control";
  return "none";
}
