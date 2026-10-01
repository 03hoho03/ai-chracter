import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useClickAway } from "react-use";

/** 색·아이콘 피커가 공유하는 열림 상태와 격자 listbox 키보드 동작.
 *
 * 패널은 `role="listbox"`라 스크린리더가 "화살표로 고르는 목록"으로 안내하는데, 예전엔 열어도 포커스가
 * 트리거에 남고 화살표가 아무것도 하지 않아 옵션에는 Tab으로만 닿았다(실측). 그래서
 * - 열면 선택된 옵션(없으면 첫 옵션)으로 포커스를 옮기고,
 * - 화살표는 격자 기준으로 움직이고(좌우 ±1, 상하 ±열 수) Home/End는 처음·끝으로 가고,
 * - 옵션은 로빙 tabindex라 Tab 한 번에 패널을 빠져나가며 그때 패널을 닫고,
 * - Esc와 선택은 패널을 닫고 포커스를 트리거로 돌려준다. */
export function useGridPicker({ optionCount, selectedIndex, columns }: {
  optionCount: number;
  selectedIndex: number;
  columns: number;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef<(HTMLButtonElement | null)[]>([]);
  useClickAway(containerRef, () => setIsOpen(false));

  useEffect(() => {
    if (isOpen) optionRefs.current[activeIndex]?.focus();
  }, [isOpen, activeIndex]);

  function toggle() {
    if (!isOpen) setActiveIndex(Math.max(0, selectedIndex));
    setIsOpen((prev) => !prev);
  }

  function closeAndRestoreFocus() {
    setIsOpen(false);
    triggerRef.current?.focus();
  }

  function handleListKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const last = optionCount - 1;
    const moves: Record<string, number> = {
      ArrowRight: Math.min(last, activeIndex + 1),
      ArrowLeft: Math.max(0, activeIndex - 1),
      ArrowDown: Math.min(last, activeIndex + columns),
      ArrowUp: Math.max(0, activeIndex - columns),
      Home: 0,
      End: last,
    };
    const next = moves[event.key];
    if (next !== undefined) {
      event.preventDefault();
      setActiveIndex(next);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closeAndRestoreFocus();
    } else if (event.key === "Tab") {
      setIsOpen(false);
    }
  }

  function optionProps(index: number) {
    return {
      ref: (element: HTMLButtonElement | null) => {
        optionRefs.current[index] = element;
      },
      tabIndex: index === activeIndex ? 0 : -1,
      onFocus: () => setActiveIndex(index),
    };
  }

  return { isOpen, containerRef, triggerRef, toggle, closeAndRestoreFocus, handleListKeyDown, optionProps };
}
