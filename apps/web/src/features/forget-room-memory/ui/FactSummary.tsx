import { cn } from "@ai-character-chat/ui/lib/utils";

import type { ChatRoomMemoryFact } from "@/entities/chat-room";

import { factHeading, turnRangeLabel } from "../model/memoryItemText";
import { MEMORY_BADGE_CLASS } from "./memoryBadge";

type FactSummaryProps = {
  fact: ChatRoomMemoryFact;
  className?: string;
};

/** 사실 하나의 본문 — 목록 행과 잊게 하기 확인 대화가 같은 모양을 쓴다. 주어·대상·속성·값을 줄이지 않고 다 보인다(이
 * 화면이 기억 내용을 열람하는 자리다). 진실 상태는 서버가 준 말 그대로 윤곽 배지로, 말한 사람은 그 옆 문장으로 둔다. */
export function FactSummary({ fact, className }: FactSummaryProps) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <span className="text-xs break-keep wrap-break-word text-muted-foreground">{factHeading(fact)}</span>
      <span className="text-sm font-semibold break-keep wrap-break-word text-foreground">{fact.value}</span>
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span className={MEMORY_BADGE_CLASS}>{fact.truthLabel}</span>
        {fact.speaker !== undefined && <span className="break-keep">{fact.speaker}의 말</span>}
        <span className="tabular-nums">{turnRangeLabel(fact.startTurn, fact.endTurn)}</span>
      </span>
    </div>
  );
}
