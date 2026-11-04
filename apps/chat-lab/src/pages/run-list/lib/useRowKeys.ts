import { useEffect } from "react";

import { isShortcutBlocked } from "@/shared/lib/isShortcutBlocked";

type RowKeyHandlers = {
  onMove: (step: 1 | -1) => void;
  onOpen: () => void;
};

/**
 * 목록 행 단축키: `j`/`k` 다음·이전 행, `Enter` 고른 행 열기.
 *
 * - 키는 `code`(자판 위치)로 본다. 한글 입력 상태에서 `j` 를 누르면 `key` 가 `ㅓ` 로 와서, `key` 로 보면 입력기를 바꿔야만 움직인다.
 * - 글을 쓰는 칸·보조키 조합·입력기 조합 중에는 손대지 않는다(`isShortcutBlocked`).
 * - `Enter` 는 아무것도 포커스하지 않았을 때만 받는다. 행 링크나 버튼에 포커스가 있으면 그 요소가 Enter 를 스스로 처리한다.
 */
export function useRowKeys({ onMove, onOpen }: RowKeyHandlers): void {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (isShortcutBlocked(event)) return;
      if (event.code === "KeyJ" || event.code === "KeyK") {
        event.preventDefault();
        onMove(event.code === "KeyJ" ? 1 : -1);
        return;
      }
      if (event.key === "Enter" && (event.target === document.body || event.target === document.documentElement)) {
        event.preventDefault();
        onOpen();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onMove, onOpen]);
}
