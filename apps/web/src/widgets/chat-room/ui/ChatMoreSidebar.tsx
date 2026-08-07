import { useEffect } from "react";
import { useAtom } from "jotai";
import { Button } from "@ai-character-chat/ui/components/button";
import { X } from "lucide-react";

import { useIsChatMoreSidebarLayout } from "../lib/useIsChatMoreSidebarLayout";
import { chatMorePanelOpenAtom } from "../model/atom";
import type { ChatMoreNavProps } from "./ChatMoreNav";
import { ChatMoreNav } from "./ChatMoreNav";

// US-004 — lg 이상의 더보기 패널. 오버레이 시트가 아니라 채팅과 폭을 나눠 갖는 인라인 <aside>다:
// 열어둔 채로 메시지를 읽고 입력·전송할 수 있어야 하므로 포털+모달 전제인 shadcn Sheet를 쓸 수 없다.
// 깊이는 그림자가 아니라 명도로 만든다(DESIGN.md Flat-at-Rest) — bg-card가 background 위 반 칸이고
// 경계는 border-l 한 줄이다. 닫기는 헤더 ⋮ 재클릭 / 이 안의 닫기 버튼 / ESC 셋 다 동작한다.
export function ChatMoreSidebar(props: ChatMoreNavProps) {
  const [open, setOpen] = useAtom(chatMorePanelOpenAtom);
  const isSidebarLayout = useIsChatMoreSidebarLayout();
  const visible = isSidebarLayout && open;

  // Sheet와 달리 Radix의 ESC 처리가 없으므로 직접 듣는다. 항목을 누르면 패널이 먼저 닫히고 모달이
  // 열리므로(ChatMoreNav) 모달과 ESC를 다툴 일은 없다.
  useEffect(() => {
    if (!visible) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [visible, setOpen]);

  if (!visible) return null;

  return (
    <aside
      aria-label="더보기"
      className="flex w-72 shrink-0 flex-col border-l border-border bg-card motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-right-10 motion-safe:duration-200"
    >
      <div className="flex shrink-0 items-center justify-between gap-2 px-4 py-3">
        <h2 className="font-heading text-base font-medium text-foreground">더보기</h2>
        <Button variant="ghost" size="icon-sm" aria-label="더보기 닫기" onClick={() => setOpen(false)}>
          <X aria-hidden className="size-4" />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pb-3">
        <ChatMoreNav {...props} />
      </div>
    </aside>
  );
}
