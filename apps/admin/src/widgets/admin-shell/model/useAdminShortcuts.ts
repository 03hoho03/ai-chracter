import { useEffect } from "react";

import { MAIN_CONTENT_ID } from "@/shared/config/landmarks";

/** 맥·아이폰·아이패드면 팔레트 단축키를 ⌘K 로 보여 준다(동작은 어느 쪽이든 ⌘·컨트롤 둘 다 받는다). */
export const IS_APPLE_PLATFORM = /Mac|iPhone|iPad/.test(navigator.userAgent);

// 글자를 받거나 인쇄 문자 키를 스스로 쓰는 자리 — 여기서 누른 `/` 는 그 자리의 것이다(편집기 본문, 팔레트 입력칸, 셀렉트
// 타입어헤드, 차트의 화살표 탐색 영역 등).
const TYPING_TARGET_SELECTOR =
  'input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="combobox"], [role="listbox"], [role="menu"], [role="application"]';

// 모달·시트(드로어·필터·조치 시트)·이탈 확인은 모두 Radix 대화상자라 이 표식이 붙는다.
const OPEN_DIALOG_SELECTOR = '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]';

type UseAdminShortcutsOptions = {
  isPaletteOpen: boolean;
  onPaletteOpenChange: (open: boolean) => void;
};

/**
 * 어드민 전역 단축키 두 개뿐이다.
 * - ⌘K / 컨트롤+K: 팔레트를 여닫는다. 입력칸 안에서도 동작한다(브라우저 주소창 검색이 가로채지 않게 기본 동작을 막는다).
 *   다른 대화상자가 열려 있으면 그 위에 겹쳐 열지 않는다.
 * - `/`: 지금 목록의 검색칸으로 간다. 글자를 받는 자리에 포커스가 있거나 대화상자가 열려 있으면 아무것도 하지 않아 `/` 가
 *   그대로 입력된다. 검색칸이 없는 화면에서도 아무것도 하지 않는다.
 * 한글 조합 중인 키는 둘 다 건드리지 않는다.
 */
export function useAdminShortcuts({ isPaletteOpen, onPaletteOpenChange }: UseAdminShortcutsOptions) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.isComposing) return;

      const isPaletteKey =
        (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && event.key.toLowerCase() === "k";
      if (isPaletteKey) {
        if (!isPaletteOpen && document.querySelector(OPEN_DIALOG_SELECTOR)) return;
        event.preventDefault();
        onPaletteOpenChange(!isPaletteOpen);
        return;
      }

      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target;
      if (target instanceof HTMLElement && (target.isContentEditable || target.closest(TYPING_TARGET_SELECTOR))) return;
      if (document.querySelector(OPEN_DIALOG_SELECTOR)) return;

      const searchInput = document.querySelector<HTMLInputElement>(`#${MAIN_CONTENT_ID} [data-filter-search]`);
      if (!searchInput) return;
      event.preventDefault();
      searchInput.focus();
      searchInput.select();
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isPaletteOpen, onPaletteOpenChange]);
}
