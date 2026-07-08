import { cn } from "@ai-character-chat/ui/lib/utils";

import type { ChatMessage } from "../../../entities/chat-room";

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <p
        className={cn(
          "max-w-[75%] whitespace-pre-wrap break-words rounded-lg px-3.5 py-2.5 text-sm leading-relaxed",
          isUser ? "bg-primary text-primary-foreground" : "bg-card text-foreground",
        )}
      >
        {message.content}
      </p>
    </div>
  );
}

// techspec-chat-common.md §5 — AI가 아직 응답하지 않은 동안(첫 토큰 도착 전) 보여주는 대기 표시.
export function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-1 rounded-lg bg-card px-3.5 py-3.5">
        {[0, 1, 2].map((dot) => (
          <span
            key={dot}
            className="size-1.5 rounded-full bg-muted-foreground motion-safe:animate-pulse"
            style={{ animationDelay: `${dot * 150}ms` }}
          />
        ))}
      </div>
    </div>
  );
}
