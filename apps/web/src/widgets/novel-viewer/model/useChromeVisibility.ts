import { useEffect, useRef, useState, type PointerEvent } from "react";

import { shouldToggleChrome } from "../lib/shouldToggleChrome";

// 누르면 그 요소 자신의 동작이 일어나는 것들. 그 위의 탭은 바를 여닫지 않는다.
const INTERACTIVE_SELECTOR = "a, button, summary, input, textarea, select, label, [role='button']";

type PointerStart = { x: number; y: number; time: number };

/**
 * 읽기 화면의 위·아래 바를 보이고 숨긴다. 처음 열 때는 숨김이다 — 정지 상태에는 본문만 빛나고, 바는 본문을 탭하거나
 * "메뉴 열기" 버튼을 누를 때만 온다. 화를 옮기면 읽기 화면이 새로 마운트돼 다시 숨김으로 시작한다.
 *
 * 숨길 때 포커스가 바 안에 있으면 **먼저** 메뉴 버튼으로 옮긴다 — 숨은 바는 `inert` 라, 그대로 두면 포커스가
 * `<body>` 로 떨어져 키보드 사용자가 문서 처음부터 다시 Tab 해야 한다. 메뉴 버튼으로 열면 포커스를 위 바의 첫
 * 요소(뒤로)로 보낸다. `inert` 가 풀린 뒤라야 포커스가 들어가므로 보인 렌더가 커밋된 뒤에 옮긴다.
 */
export function useChromeVisibility({ onHide }: { onHide: () => void }) {
  const [isVisible, setIsVisible] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const topBarRef = useRef<HTMLElement>(null);
  const bottomBarRef = useRef<HTMLDivElement>(null);
  const shouldFocusTopBarRef = useRef(false);
  const pointerStartRef = useRef<PointerStart | undefined>(undefined);

  useEffect(() => {
    if (!isVisible || !shouldFocusTopBarRef.current) return;
    shouldFocusTopBarRef.current = false;
    topBarRef.current?.querySelector<HTMLElement>("a, button")?.focus();
  }, [isVisible]);

  function isFocusInBars(): boolean {
    const active = document.activeElement;
    if (active === null) return false;
    return topBarRef.current?.contains(active) === true || bottomBarRef.current?.contains(active) === true;
  }

  function hide() {
    if (isFocusInBars()) menuButtonRef.current?.focus();
    onHide();
    setIsVisible(false);
  }

  function show({ focusTopBar }: { focusTopBar: boolean }) {
    shouldFocusTopBarRef.current = focusTopBar;
    setIsVisible(true);
  }

  /** 본문 위의 누름 시작. 탭 판별은 뗄 때 한다. 주 포인터의 왼쪽 버튼(터치·펜 포함)만 본다. */
  function handlePointerDown(event: PointerEvent<HTMLElement>) {
    if (!event.isPrimary || event.button !== 0) {
      pointerStartRef.current = undefined;
      return;
    }
    pointerStartRef.current = { x: event.clientX, y: event.clientY, time: event.timeStamp };
  }

  /** 본문 위의 뗌. 탭이면 `onTap` 을 부른다(무엇을 여닫을지는 호출부가 정한다 — 보기 설정이 열려 있으면 그것만 닫는다). */
  function handlePointerUp(event: PointerEvent<HTMLElement>, onTap: () => void) {
    const start = pointerStartRef.current;
    pointerStartRef.current = undefined;
    if (start === undefined || !event.isPrimary) return;
    const target = event.target;
    const isTap = shouldToggleChrome({
      dx: event.clientX - start.x,
      dy: event.clientY - start.y,
      dt: event.timeStamp - start.time,
      selectionCollapsed: window.getSelection()?.isCollapsed ?? true,
      targetIsInteractive: target instanceof Element && target.closest(INTERACTIVE_SELECTOR) !== null,
    });
    if (isTap) onTap();
  }

  return {
    isVisible,
    show,
    hide,
    menuButtonRef,
    topBarRef,
    bottomBarRef,
    handlePointerDown,
    handlePointerUp,
  };
}
