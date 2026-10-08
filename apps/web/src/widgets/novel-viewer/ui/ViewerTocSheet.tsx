import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@ai-character-chat/ui/components/sheet";
import { useId, useRef } from "react";

import { EpisodeTocList, NovelReadProgressSummary, toNovelReadProgress, type NovelDetailResponse } from "@/entities/novel";

type ViewerTocSheetProps = {
  novel: NovelDetailResponse;
  currentChapterId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 닫힌 뒤 포커스를 돌려줄 요소. 시트를 여는 자리가 둘(위 바·화 끝)이라 연 자리를 호출부가 알려 준다. */
  returnFocusTo: () => HTMLElement | null;
};

/** 읽기 화면의 목차 — 오른쪽 시트. 위 바의 목차 버튼이 오른쪽 끝에 있어 같은 쪽에서 나온다. 열 때 지금 화를 목록
 * 가운데로 올리고 그 줄에 포커스를 둔다. 다른 화를 누르면 시트를 닫고 그 화로 간다.
 *
 * 닫힐 때 포커스는 연 자리로 돌린다 — 트리거 없이 여는 시트라 기본 동작으로는 돌아갈 곳이 없다. 연 자리가 그사이
 * 숨은 바 안이면(`inert`) 돌려줄 수 없어 브라우저 기본에 맡긴다. */
export function ViewerTocSheet({ novel, currentChapterId, open, onOpenChange, returnFocusTo }: ViewerTocSheetProps) {
  const progressId = useId();
  const listRef = useRef<HTMLDivElement>(null);
  const progress = toNovelReadProgress(novel.chapters);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        aria-describedby={progressId}
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
        <SheetHeader className="pr-14">
          <NovelReadProgressSummary heading={<SheetTitle>목차</SheetTitle>} progress={progress} labelId={progressId} />
        </SheetHeader>
        <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-2 pt-1 pb-4">
          <EpisodeTocList
            novelId={novel.id}
            chapters={novel.chapters}
            lastReadChapterId={novel.lastRead?.chapterId}
            currentChapterId={currentChapterId}
            surface="sheet"
            onNavigate={() => onOpenChange(false)}
          />
        </div>
      </SheetContent>
    </Sheet>
  );
}
