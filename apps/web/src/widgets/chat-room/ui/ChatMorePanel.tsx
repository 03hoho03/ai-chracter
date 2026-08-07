import { useAtom } from "jotai";
import { Button } from "@ai-character-chat/ui/components/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@ai-character-chat/ui/components/sheet";
import { MoreVertical } from "lucide-react";

import { useIsChatMoreSidebarLayout } from "../lib/useIsChatMoreSidebarLayout";
import { chatMorePanelOpenAtom } from "../model/atom";
import type { ChatMoreNavProps } from "./ChatMoreNav";
import { ChatMoreNav } from "./ChatMoreNav";

// 채팅 헤더의 ⋮ 트리거. US-004 이후 패널 자체는 뷰포트에 따라 두 곳에서 그려진다 —
// lg 이상은 ChatRoomView가 배치한 인라인 <aside>(ChatMoreSidebar), lg 미만은 여기의 Sheet.
// 어느 쪽이든 열림 상태는 chatMorePanelOpenAtom 하나이고 항목 목록은 ChatMoreNav 하나다.
export function ChatMorePanel(props: ChatMoreNavProps) {
  const [open, setOpen] = useAtom(chatMorePanelOpenAtom);
  const isSidebarLayout = useIsChatMoreSidebarLayout();

  if (isSidebarLayout) {
    return (
      <Button variant="ghost" size="icon" aria-label="더보기" aria-expanded={open} onClick={() => setOpen(!open)}>
        <MoreVertical aria-hidden className="size-4" />
      </Button>
    );
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="더보기">
          <MoreVertical aria-hidden className="size-4" />
        </Button>
      </SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>더보기</SheetTitle>
        </SheetHeader>
        <ChatMoreNav {...props} />
      </SheetContent>
    </Sheet>
  );
}
