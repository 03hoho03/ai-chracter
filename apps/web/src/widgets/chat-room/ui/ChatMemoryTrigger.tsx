import type { RefObject } from "react";
import { useAtom } from "jotai";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@ai-character-chat/ui/components/dialog";
import { NotebookPen } from "lucide-react";

import { RoomMemoryEditor } from "@/features/edit-room-memory";

import { MEMORY_PANEL_DESCRIPTION } from "../config/memoryPanel";
import { confirmClearMemoryNote } from "../lib/confirmClearMemoryNote";
import { useIsChatMoreSidebarLayout } from "../lib/useIsChatMoreSidebarLayout";
import { chatSidePanelAtom } from "../model/atoms";

export type ChatMemoryTriggerProps = {
  roomId: string;
  triggerRef: RefObject<HTMLButtonElement | null>;
};

// 채팅 헤더의 기억 노트 버튼. lg 이상은 더보기와 같은 자리의 인라인 패널(ChatMemorySidebar)을 여닫고,
// 그 미만은 여기서 Dialog를 연다 — 편집 칸이 있어 바닥 드롭업 시트면 키보드가 올라올 때 스크롤 영역이 두 겹이
// 된다(RoomPersonaModal과 같은 이유). 열림 상태는 더보기와 같은 atom이라 둘이 함께 열리지 않는다.
export function ChatMemoryTrigger({ roomId, triggerRef }: ChatMemoryTriggerProps) {
  const [panel, setPanel] = useAtom(chatSidePanelAtom);
  const isSidebarLayout = useIsChatMoreSidebarLayout();
  const isOpen = panel === "memory";

  if (isSidebarLayout) {
    return (
      <Button
        ref={triggerRef}
        variant="ghost"
        size="icon"
        aria-label="기억 노트"
        aria-expanded={isOpen}
        onClick={() => setPanel(isOpen ? undefined : "memory")}
      >
        <NotebookPen aria-hidden className="size-4" />
      </Button>
    );
  }

  return (
    <Dialog open={isOpen} onOpenChange={(open) => setPanel(open ? "memory" : undefined)}>
      <DialogTrigger asChild>
        <Button ref={triggerRef} variant="ghost" size="icon" aria-label="기억 노트">
          <NotebookPen aria-hidden className="size-4" />
        </Button>
      </DialogTrigger>
      {/* 요약 1,500자 + 노트 편집 칸이라 길어진다 — 최대 높이와 내부 스크롤은 호출부 몫이다(packages/ui/CLAUDE.md). */}
      <DialogContent className="max-h-dialog overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>기억 노트</DialogTitle>
          <DialogDescription className="break-keep">{MEMORY_PANEL_DESCRIPTION}</DialogDescription>
        </DialogHeader>
        <RoomMemoryEditor roomId={roomId} onClearNoteRequest={confirmClearMemoryNote} />
      </DialogContent>
    </Dialog>
  );
}
