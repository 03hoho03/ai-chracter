import { Sheet, SheetContent, SheetHeader } from "@ai-character-chat/ui/components/sheet";
import { useRef, type ReactNode } from "react";

/** 읽기 화면이 목차 시트를 그릴 때 넘겨주는 열림 상태. 목록과 머리는 경로(내 소설·노벨)마다 달라 호출부가 채운다. */
export type ViewerTocSheetControl = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 닫힌 뒤 포커스를 돌려줄 요소. 시트를 여는 자리가 둘(위 바·화 끝)이라 연 자리를 읽기 화면이 알려 준다. */
  returnFocusTo: () => HTMLElement | null;
};

type ViewerTocSheetProps = ViewerTocSheetControl & {
  /** 머리 — `SheetTitle` 을 품는다. */
  heading: ReactNode;
  /** 머리 밑 설명(읽은 정도 등)의 id. 시트의 설명으로 읽힌다. */
  descriptionId?: string;
  /** 화 목록. 지금 화 줄에 `aria-current="page"` 를 단다. */
  children: ReactNode;
};

/** 읽기 화면의 목차 — 오른쪽 시트. 위 바의 목차 버튼이 오른쪽 끝에 있어 같은 쪽에서 나온다. 열 때 지금 화를 목록
 * 가운데로 올리고 그 줄에 포커스를 둔다. 다른 화를 누르면 시트를 닫고 그 화로 간다(목록이 `onOpenChange(false)` 를
 * 부른다).
 *
 * 닫힐 때 포커스는 연 자리로 돌린다 — 트리거 없이 여는 시트라 기본 동작으로는 돌아갈 곳이 없다. 연 자리가 그사이
 * 숨은 바 안이면(`inert`) 돌려줄 수 없어 브라우저 기본에 맡긴다. */
export function ViewerTocSheet({ open, onOpenChange, returnFocusTo, heading, descriptionId, children }: ViewerTocSheetProps) {
  const listRef = useRef<HTMLDivElement>(null);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        aria-describedby={descriptionId}
        onOpenAutoFocus={(event) => {
          const current = listRef.current?.querySelector<HTMLElement>('[aria-current="page"]');
          if (current === null || current === undefined) return;
          event.preventDefault();
          current.scrollIntoView({ block: "center" });
          current.focus();
        }}
        onCloseAutoFocus={(event) => {
          const target = returnFocusTo();
          if (target === null || !target.isConnected || target.closest("[inert]") !== null) return;
          event.preventDefault();
          target.focus();
        }}
      >
        {/* 오른쪽 위 닫기(X)와 겹치지 않게 머리 오른쪽을 비운다. */}
        <SheetHeader className="pr-14">{heading}</SheetHeader>
        <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-2 pt-1 pb-4">
          {children}
        </div>
      </SheetContent>
    </Sheet>
  );
}
