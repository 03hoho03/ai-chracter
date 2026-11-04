import { useEffect, useRef } from "react";

import { isShortcutBlocked } from "@/shared/lib/isShortcutBlocked";

import { INSPECTOR_TABS } from "../model/runDetailSearch";

type DetailKeyHandlers = {
  onMoveTurn: (step: 1 | -1) => void;
  onMoveAttempt: (step: 1 | -1) => void;
  onFocusSearch: () => void;
  onStepMatch: (step: 1 | -1) => void;
  onInspectorTab: (index: number) => void;
  onFocusTimeline: () => void;
  onEscape: () => void;
};

/** 검사기 탭 숫자 키 — 탭 목록에서 만들어, 탭을 더하면 그 숫자 키도 함께 선다(`onInspectorTab` 은 탭 목록의 순번을 받는다). */
const INSPECTOR_KEYS = INSPECTOR_TABS.map((_, index) => `Digit${index + 1}`);

/**
 * 런 상세 단축키: `j`/`k` 다음·이전 턴, `[`/`]` 이전·다음 시도, `/` 원문 검색, `n`/`N` 다음·이전 일치, `1`~`4` 검사기 탭,
 * `g` 타임라인, `Esc` 펼친 목록 닫기.
 *
 * - 키는 `code`(자판 위치)로 본다 — 한글 입력 상태에서도 입력기를 바꾸지 않고 움직인다(목록 화면과 같다).
 * - 글을 쓰는 칸·보조키 조합·입력기 조합 중에는 손대지 않는다(목록 화면과 같은 판정). 검색 칸 안의 Enter·Esc 는 그 칸이 맡는다.
 * - 처리기는 렌더마다 바뀌어도 창 구독을 다시 걸지 않게 ref 로 읽는다 — `j` 를 누르고 있으면 렌더가 키 반복만큼 일어난다.
 *   ref 는 그린 뒤에 바꾼다(키 입력은 늘 그린 뒤에 오므로 마지막으로 그린 화면의 처리기가 받는다).
 */
export function useDetailKeys(handlers: DetailKeyHandlers): void {
  const handlersRef = useRef(handlers);
  useEffect(() => {
    handlersRef.current = handlers;
  });

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (isShortcutBlocked(event)) return;
      const current = handlersRef.current;
      const inspectorIndex = INSPECTOR_KEYS.indexOf(event.code);
      if (inspectorIndex !== -1 && !event.shiftKey) {
        event.preventDefault();
        current.onInspectorTab(inspectorIndex);
        return;
      }
      switch (event.code) {
        case "KeyJ":
        case "KeyK":
          event.preventDefault();
          current.onMoveTurn(event.code === "KeyJ" ? 1 : -1);
          return;
        case "BracketLeft":
        case "BracketRight":
          event.preventDefault();
          current.onMoveAttempt(event.code === "BracketRight" ? 1 : -1);
          return;
        case "Slash":
          event.preventDefault();
          current.onFocusSearch();
          return;
        case "KeyN":
          event.preventDefault();
          current.onStepMatch(event.shiftKey ? -1 : 1);
          return;
        case "KeyG":
          event.preventDefault();
          current.onFocusTimeline();
          return;
        case "Escape":
          current.onEscape();
          return;
        default:
          return;
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);
}
