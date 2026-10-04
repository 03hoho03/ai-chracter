import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { useBlocker, type ShouldBlockFn } from "@tanstack/react-router";
import { useCallback, useRef } from "react";

import { MAIN_CONTENT_ID } from "@/shared/config/landmarks";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";

type UnsavedChangesGuardProps = {
  /** 저장하지 않은 변경이 있는지. 저장·게시가 성공한 직후에는 거짓이어야 한다(그때 떠나도 잃는 것이 없다). */
  isDirty: boolean;
};


/**
 * 편집 화면(약관·공지·프롬프트)에서 저장하지 않은 채 다른 화면으로 가려 하면 확인을 받는다. 화면당 하나만 둔다 — 둘이면
 * 확인 창이 차례로 두 번 뜬다.
 *
 * 차단은 변경이 있는 동안에만 건다(`disabled`). 그래서 새로고침·탭 닫기의 브라우저 확인(`beforeunload`)도 그동안만
 * 뜨고, 저장하면 바로 풀린다. 저장 직후 같은 처리 안에서 이동하는 곳(새 공지를 만들고 그 주소로 가는 것)은 화면이 아직
 * 다시 그려지지 않아 차단이 남아 있으므로 그 이동에 `ignoreBlocker` 를 준다.
 */
export function UnsavedChangesGuard({ isDirty }: UnsavedChangesGuardProps) {
  // 이동을 막는 순간 포커스가 있던 곳(누른 내비 링크 등). 창이 닫힐 때 그리로 돌려준다 — 이 창은 트리거 없이 열려
  // 그냥 두면 포커스가 `<body>` 로 떨어진다. 창이 열릴 때 읽으면 이미 늦다(실측: 그때는 링크에 포커스가 없다).
  const returnFocusRef = useRef<Element | null>(null);
  // 다른 화면으로 갈 때만 막는다 — 같은 화면 안의 search 변경(탭·페이지)은 편집 내용을 잃지 않는다. 함수가 바뀌면
  // 라우터가 차단을 다시 걸므로 참조를 고정한다.
  const shouldBlockFn = useCallback<ShouldBlockFn>(({ current, next }) => {
    const isLeaving = current.pathname !== next.pathname;
    if (isLeaving) returnFocusRef.current = document.activeElement;
    return isLeaving;
  }, []);
  const blocker = useBlocker({ shouldBlockFn, disabled: !isDirty, withResolver: true });

  return (
    <Dialog open={blocker.status === "blocked"} onOpenChange={(open) => !open && blocker.reset?.()}>
      <DialogContent
        className="sm:max-w-sm"
        onOpenAutoFocus={focusInitialElement}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          const target = returnFocusRef.current;
          returnFocusRef.current = null;
          // 드로어 안 링크였다면 드로어가 닫히며 사라졌다 — 그때는 본문으로 보낸다.
          if (target instanceof HTMLElement && target.isConnected) {
            target.focus();
          } else {
            document.getElementById(MAIN_CONTENT_ID)?.focus();
          }
        }}
      >
        <DialogHeader>
          <DialogTitle>저장하지 않은 변경이 있어요</DialogTitle>
          <DialogDescription className="break-keep">이 화면을 떠나면 변경 내용이 사라져요.</DialogDescription>
        </DialogHeader>
        {/* 첫 포커스는 머무는 쪽이다 — 무심코 Enter 를 눌러도 편집 내용을 잃지 않게. */}
        <DialogFooter>
          <Button type="button" variant="outline" autoFocus data-initial-focus onClick={() => blocker.reset?.()}>
            계속 편집
          </Button>
          <Button type="button" variant="destructive" onClick={() => blocker.proceed?.()}>
            떠나기
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
