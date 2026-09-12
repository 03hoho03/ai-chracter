import { Sparkles } from "lucide-react";

// techspec-chat-story.md §5 — 엔딩 도달을 알리는 구분선. 바로 아래 오는 에필로그 말풍선(MessageBubble,
// 일반 AI 메시지와 동일한 스타일)과 짝을 이뤄, 그 메시지가 엔딩임을 표시하는 역할만 한다.
export function EndingDivider({ endingName }: { endingName?: string }) {
  return (
    <div role="separator" aria-label="엔딩 도달" className="flex items-center gap-3 py-1">
      <div className="h-px flex-1 bg-border" />
      <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-secondary px-3 py-1 text-xs font-medium text-secondary-foreground">
        <Sparkles aria-hidden className="size-3.5" />
        {endingName ? `엔딩 · ${endingName}` : "엔딩에 도달했어요"}
      </span>
      <div className="h-px flex-1 bg-border" />
    </div>
  );
}
