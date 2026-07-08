import { cn } from "@ai-character-chat/ui/lib/utils";
import { Sparkles } from "lucide-react";

import type { ChatMessage } from "../../../entities/chat-room";

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex flex-col gap-1.5", isUser ? "items-end" : "items-start")}>
      <p
        className={cn(
          "max-w-[75%] whitespace-pre-wrap break-words rounded-lg px-3.5 py-2.5 text-sm leading-relaxed",
          isUser ? "bg-primary text-primary-foreground" : "bg-card text-foreground",
        )}
      >
        {message.content}
      </p>
      {message.imageUrl && (
        // US-073 — 상황별 이미지는 원본 비율 그대로 보여준다(크롭 없음). max-w/max-h만 지정하면
        // object-fit 없이도 브라우저가 원본 비율을 유지한 채 그 안에 맞춰 축소한다.
        <img src={message.imageUrl} alt="대화 중 노출된 이미지" className="max-h-80 max-w-[75%] rounded-lg" />
      )}
    </div>
  );
}

// techspec-chat-story.md §5 — 엔딩 도달을 알리는 구분선. 바로 아래 오는 에필로그 말풍선(MessageBubble,
// 일반 AI 메시지와 동일한 스타일)과 짝을 이뤄, 그 메시지가 엔딩임을 표시하는 역할만 한다.
export function EndingDivider({ endingName }: { endingName?: string }) {
  return (
    <div role="separator" aria-label="엔딩 도달" className="flex items-center gap-3 py-1">
      <div className="h-px flex-1 bg-border" />
      <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-[oklch(0.72_0.14_50)] px-3 py-1 text-xs font-medium text-white">
        <Sparkles aria-hidden className="size-3.5" />
        {endingName ? `엔딩 · ${endingName}` : "엔딩에 도달했어요"}
      </span>
      <div className="h-px flex-1 bg-border" />
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
