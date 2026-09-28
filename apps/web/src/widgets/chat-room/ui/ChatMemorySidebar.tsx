import { useEffect, useRef } from "react";
import { useAtom } from "jotai";
import { Button } from "@ai-character-chat/ui/components/button";
import { X } from "lucide-react";

import { RoomMemoryEditor } from "@/features/edit-room-memory";

import { MEMORY_PANEL_DESCRIPTION, confirmClearMemoryNote } from "../lib/confirmClearMemoryNote";
import { useIsChatMoreSidebarLayout } from "../lib/useIsChatMoreSidebarLayout";
import { chatSidePanelAtom } from "../model/atoms";
import type { ChatMemoryTriggerProps } from "./ChatMemoryTrigger";

type ChatMemorySidebarProps = ChatMemoryTriggerProps;

// lg 이상의 기억 노트 패널. 더보기 사이드바(ChatMoreSidebar)와 같은 슬롯·같은 표면(bg-card + border-l)이고,
// 열어 둔 채 대화를 읽으며 노트를 고칠 수 있어야 해서 오버레이가 아니다. 폭만 넓다(편집 칸이 있다).
// 등장은 페이드만 — 인라인 flex 아이템이라 슬라이드는 문서를 가로로 넘치게 한다(ChatMoreSidebar 주석).
//
// 포커스: 열면 제목으로 옮기고, 닫으면(닫기 버튼·ESC) 헤더의 버튼으로 돌린다 — 트랩이 없는 인라인 패널이라
// 옮기지 않으면 키보드 사용자는 패널이 열렸는지 모른다.
export function ChatMemorySidebar({ roomId, triggerRef }: ChatMemorySidebarProps) {
  const [panel, setPanel] = useAtom(chatSidePanelAtom);
  const isSidebarLayout = useIsChatMoreSidebarLayout();
  const isVisible = isSidebarLayout && panel === "memory";
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (isVisible) headingRef.current?.focus();
  }, [isVisible]);

  if (!isVisible) return null;

  function handleClose() {
    setPanel(null);
    triggerRef.current?.focus();
  }

  return (
    <aside
      aria-labelledby="chat-memory-heading"
      // ESC는 패널 안에 포커스가 있을 때만 닫는다 — 창 전체에서 들으면 여기서 띄운 확인 모달을 ESC로 닫을 때
      // 패널까지 함께 닫혀 쓰던 노트가 사라진다.
      onKeyDown={(event) => {
        if (event.key === "Escape") handleClose();
      }}
      className="flex w-80 shrink-0 flex-col border-l border-border bg-card motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200"
    >
      <div className="flex shrink-0 items-center justify-between gap-2 px-4 py-3">
        <h2
          id="chat-memory-heading"
          ref={headingRef}
          tabIndex={-1}
          className="font-heading text-lg font-medium text-foreground outline-none"
        >
          기억 노트
        </h2>
        <Button variant="ghost" size="icon-sm" aria-label="기억 노트 닫기" className="hover:bg-secondary" onClick={handleClose}>
          <X aria-hidden className="size-4" />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
        <p className="mb-5 text-xs break-keep text-muted-foreground">{MEMORY_PANEL_DESCRIPTION}</p>
        <RoomMemoryEditor roomId={roomId} confirmClearNote={confirmClearMemoryNote} />
      </div>
    </aside>
  );
}
