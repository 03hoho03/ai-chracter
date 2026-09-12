import { cn } from "@ai-character-chat/ui/lib/utils";

// STYLE-01 — 인덱스별 정적 지연값이라 인라인 style 대신 클래스 배열로 고정한다(0/150/300ms).
const DOT_DELAY_CLASSES = ["", "[animation-delay:150ms]", "[animation-delay:300ms]"];

// techspec-chat-common.md §5 — AI가 아직 응답하지 않은 동안(첫 토큰 도착 전) 보여주는 대기 표시.
export function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-1 rounded-lg bg-card px-3.5 py-3.5">
        {DOT_DELAY_CLASSES.map((delayClass, index) => (
          <span
            key={index}
            className={cn("size-1.5 rounded-full bg-muted-foreground motion-safe:animate-pulse", delayClass)}
          />
        ))}
      </div>
    </div>
  );
}
