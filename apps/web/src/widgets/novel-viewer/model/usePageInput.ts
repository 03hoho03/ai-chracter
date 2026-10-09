import { useEffect, useLayoutEffect, useRef, type DragEvent, type MouseEvent, type PointerEvent, type RefObject } from "react";

import { toPageGesture } from "../lib/pageGesture";
import { toPageKeyAction, type PageKeyFocus } from "../lib/pageKey";
import { isMouseReleasedElsewhere, shouldGuardEdgeTouch, shouldSuppressClick } from "../lib/pointerGuard";
import { reduceWheel, type WheelTurnState } from "../lib/wheelTurn";
import { INTERACTIVE_SELECTOR } from "./useChromeVisibility";
import type { PagedDirectMove, PagedReaderHandle } from "./usePagedReader";

/** 가로로 이만큼 움직여야 끌기로 친다 — 탭으로 치는 거리와 같은 값이라, 탭이 아닌 가로 손짓은 곧바로 쪽을 끈다. */
const DRAG_START_PX = 10;
/** 손을 뗄 때의 속도를 이 시간 안의 움직임으로 잰다. 더 길면 멈췄다 놓은 손짓도 빠르게 튕긴 것으로 읽힌다. */
const VELOCITY_WINDOW_MS = 100;

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
  /** 손짓을 받는 본문 상자. */
  viewportRef: RefObject<HTMLElement | null>;
  /** 휠·가장자리 터치를 받는 범위 — 본문 상자와 그 옆 거터 넘김 버튼을 함께 담는다. */
  wheelRootRef: RefObject<HTMLElement | null>;
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
 *   놓은 직후의 click 은 막는다 — 링크 위에서 시작한 끌기가 작가의 말·다음 화로 새지 않게. 막는 것은 뗌 바로 뒤의
 *   포인터 click 뿐이다(`shouldSuppressClick`) — 터치 스와이프는 click 을 만들지 않아 표시만 남는데, 그것이 나중의
 *   키보드·보조기기 활성화를 삼키면 안 된다.
 * - **끊긴 누름**: 끄는 도중 둘째 손가락이 닿아도 그 누름은 무시하고 첫 손가락의 끌기를 이어 간다. 브라우저가 핀치를
 *   잡아 취소를 보내면 어느 손가락의 취소든 끌던 쪽을 제자리로 돌린다. 마우스를 본문 밖(겹쳐 뜬 바·넘김 버튼 위)에서
 *   놓아 본문이 뗌을 받지 못했으면, 다음 움직임에서 버튼이 놓인 것을 보고 취소로 친다 — 그러지 않으면 버튼 없이
 *   움직이는 마우스를 쪽이 따라간다.
 * - **확대**: 핀치로 확대한 동안의 손짓은 확대한 화면을 둘러보는 것이라 넘기지 않는다(가운데 탭의 바 토글은 둔다).
 * - **휠**: 한 번 굴리거나 밀면 한 쪽(`reduceWheel`). 확대 단축(Ctrl+휠·트랙패드 핀치)은 브라우저에 맡기고, 본문과
 *   거터 넘김 버튼 위의 그 밖의 휠은 기본 동작을 막는다. 트랙패드 가로 밀기가 브라우저의 뒤로 가기 손짓으로 새는 것은 페이지 모드 동안
 *   문서 루트의 가로 오버스크롤을 꺼서 막는다 — 본문 위뿐 아니라 거터 넘김 버튼·열린 바 위에서 밀어도 같고, 보기 설정
 *   패널·목차 시트 안의 스크롤은 그대로다(오버스크롤 설정은 그 요소의 끝에서 이어지는 동작만 바꾼다).
 * - **키**: 창에서 버블 단계로 듣고(다른 처리기가 이미 쓴 키는 건너뛴다), 포커스 자리를 가려 `toPageKeyAction` 에
 *   맡긴다. `Esc` 는 셸이 따로 맡는다.
 * - **화면 가장자리**: iOS 의 가장자리 스와이프(뒤로 가기)가 쪽 넘김과 부딪혀, 가장자리에서 시작한 터치의 기본 동작을
 *   막아 본다(`shouldGuardEdgeTouch` — 링크·버튼 위는 제외). 웹에서는 확실히 막을 수 없어 실기기에서 확인할 일이다.
 */
export function usePageInput(options: UsePageInputOptions) {
  const { viewportRef, wheelRootRef, handle, directMove, pageWidth, isSettingsOpen, onBodyTap } = options;
  const optionsRef = useRef(options);
  const startRef = useRef<PointerStart | undefined>(undefined);
  const samplesRef = useRef<PointerSample[]>([]);
  const isDraggingRef = useRef(false);
  // 끌기로 끝난 뗌의 시각. 그 바로 뒤의 포인터 click 만 막는다.
  const suppressClickAtRef = useRef<number | undefined>(undefined);
  const wheelStateRef = useRef<WheelTurnState>({});

  // 창·본문에 직접 단 처리기는 처음 한 번 달아 두므로 지금 값을 이 ref 로 읽는다.
  useLayoutEffect(() => {
    optionsRef.current = options;
  });

  function setDragging(isDragging: boolean) {
    isDraggingRef.current = isDragging;
    viewportRef.current?.toggleAttribute("data-dragging", isDragging);
  }

  /** 진행 중인 누름을 끝낸다. 끌던 중이면 지금 화면으로 돌아간다. */
  function cancelPress() {
    startRef.current = undefined;
    if (isDraggingRef.current) directMove.release(0);
    setDragging(false);
  }

  function handlePointerDown(event: PointerEvent<HTMLElement>) {
    // 끄는 도중 닿은 둘째 손가락은 첫 손가락의 누름을 건드리지 않는다.
    if (!event.isPrimary) return;
    // 본문이 뗌을 받지 못한 채 남은 누름이 있으면 새 누름 전에 정리한다.
    cancelPress();
    suppressClickAtRef.current = undefined;
    if (event.button !== 0) return;
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
    if (isMouseReleasedElsewhere(event)) {
      cancelPress();
      return;
    }
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
    if (start === undefined || event.pointerId !== start.pointerId) return;
    startRef.current = undefined;
    const wasDragging = isDraggingRef.current;
    setDragging(false);

    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    if (Math.hypot(dx, dy) >= DRAG_START_PX) suppressClickAtRef.current = event.timeStamp;
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

  // 끄는 중이면 어느 포인터의 취소든 끌기를 끝낸다 — 핀치를 잡은 브라우저는 둘째 손가락의 취소만 보낼 수도 있다.
  function handlePointerCancel(event: PointerEvent<HTMLElement>) {
    if (isDraggingRef.current || startRef.current?.pointerId === event.pointerId) cancelPress();
  }

  function handleClickCapture(event: MouseEvent<HTMLElement>) {
    const suppressedAt = suppressClickAtRef.current;
    suppressClickAtRef.current = undefined;
    if (!shouldSuppressClick({ suppressedAt, clickAt: event.timeStamp, detail: event.detail })) return;
    event.preventDefault();
    event.stopPropagation();
  }

  // 링크·이미지를 끌면 브라우저의 끌어 놓기가 시작돼 포인터 흐름을 가로챈다.
  function handleDragStart(event: DragEvent<HTMLElement>) {
    event.preventDefault();
  }

  useEffect(() => {
    const root = document.documentElement;
    const previous = root.style.overscrollBehaviorX;
    root.style.overscrollBehaviorX = "none";
    return () => {
      root.style.overscrollBehaviorX = previous;
    };
  }, []);

  // 휠과 화면 가장자리 터치. 둘 다 기본 동작을 막아야 해서 수동적이지 않은 처리기로 직접 단다. 거터 넘김 버튼 위에서
  // 굴려도 넘어가게 본문 상자가 아니라 버튼까지 담은 범위에 단다(바·설정 패널·목차 시트는 이 범위 밖이라 그 안의
  // 스크롤은 그대로다).
  useEffect(() => {
    const viewport = wheelRootRef.current;
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
      if (touch === null) return;
      const target = event.target;
      const isGuarded = shouldGuardEdgeTouch({
        clientX: touch.clientX,
        viewportWidth: window.innerWidth,
        touchCount: event.touches.length,
        isOnInteractive: target instanceof Element && target.closest(INTERACTIVE_SELECTOR) !== null,
      });
      if (isGuarded) event.preventDefault();
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
