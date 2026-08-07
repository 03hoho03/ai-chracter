import { useAtom } from "jotai";
import { Button } from "@ai-character-chat/ui/components/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@ai-character-chat/ui/components/sheet";
import { MoreVertical } from "lucide-react";

import { useIsChatMoreSidebarLayout } from "../lib/useIsChatMoreSidebarLayout";
import { chatMorePanelOpenAtom } from "../model/atom";
import type { ChatMoreNavProps } from "./ChatMoreNav";
import { ChatMoreNav } from "./ChatMoreNav";

// 채팅 헤더의 ⋮ 트리거. US-004 이후 패널 자체는 뷰포트에 따라 두 곳에서 그려진다 —
// lg 이상은 ChatRoomView가 배치한 인라인 <aside>(ChatMoreSidebar), lg 미만은 여기의 드롭업 Sheet.
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
      {/* US-005 — lg 미만은 우측 시트가 아니라 바닥에서 올라오는 드롭업이다. 목적은 패널을 여는 동안에도
          "지금 누구와 대화 중인지"(아바타·캐릭터명·방 이름)가 계속 보이는 것이므로 시트 상단을 채팅 헤더
          바로 아래에 붙인다. 390x844에서 실측한 값이 그 118px이다 — 전역 헤더 56 + border 1 + 채팅 헤더
          60 + border 1. ChatRoomView의 h-[calc(100dvh-3.5rem)]와 같은 수동 미러링이다(DESIGN.md).
          전역 헤더까지 보이게 할지는 이 실측으로 결론이 났다: 전역 헤더(0~57)가 채팅 헤더(57~118) 위에
          있으므로 채팅 헤더를 남기면 전역 헤더는 반드시 함께 남는다 — 둘을 따로 고를 수 없다. 시트를
          57px까지 올려 채팅 헤더를 덮는 반대 선택지는 이 스토리의 목적과 정면으로 어긋나서 버렸다. */}
      <SheetContent side="bottom" className="top-[118px] rounded-t-xl">
        <SheetHeader>
          <SheetTitle>더보기</SheetTitle>
        </SheetHeader>
        {/* 시트가 헤더 아래 전체를 채우므로 항목이 넘칠 때 페이지가 아니라 이 영역만 스크롤되게 한다. */}
        <div className="min-h-0 flex-1 overflow-y-auto pb-3">
          <ChatMoreNav {...props} />
        </div>
      </SheetContent>
    </Sheet>
  );
}
