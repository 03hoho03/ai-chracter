import { useEffect, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { MoreHorizontal, Pencil, RotateCw, Sparkles, Trash2 } from "lucide-react";

import type { ChatMessage } from "../../../entities/chat-room";

type MessageBubbleProps = {
  message: ChatMessage;
  // US-077 — 재생성/수정/삭제 액션. 세 콜백 모두 optional인 이유는 스트리밍 중 임시 버블
  // (streaming/ending-epilogue, ChatRoomView.tsx 참고)에는 실제 messageId가 없어 어떤 액션도
  // 붙일 수 없기 때문 — onDelete가 없으면 "⋯" 메뉴 자체를 렌더링하지 않는다.
  canRegenerate?: boolean;
  isEditing?: boolean;
  disabled?: boolean;
  onRegenerate?: () => void;
  onStartEdit?: () => void;
  onCancelEdit?: () => void;
  onSaveEdit?: (text: string) => void;
  onDelete?: () => void;
};

export function MessageBubble({
  message,
  canRegenerate = false,
  isEditing = false,
  disabled = false,
  onRegenerate,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onDelete,
}: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [draft, setDraft] = useState(message.content);

  useEffect(() => {
    if (isEditing) setDraft(message.content);
  }, [isEditing, message.content]);

  if (isEditing) {
    const trimmed = draft.trim();
    return (
      <div className="flex flex-col items-end gap-1.5">
        <Textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              if (trimmed) onSaveEdit?.(trimmed);
            } else if (event.key === "Escape") {
              onCancelEdit?.();
            }
          }}
          autoFocus
          rows={2}
          className="max-w-[75%] resize-none"
        />
        <div className="flex gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onCancelEdit}>
            취소
          </Button>
          <Button type="button" size="sm" disabled={!trimmed} onClick={() => onSaveEdit?.(trimmed)}>
            저장
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col gap-1.5", isUser ? "items-end" : "items-start")}>
      <div className={cn("flex items-end gap-1", isUser ? "flex-row-reverse" : "flex-row")}>
        <p
          className={cn(
            "max-w-[75%] whitespace-pre-wrap break-words rounded-lg px-3.5 py-2.5 text-sm leading-relaxed",
            isUser ? "bg-primary text-primary-foreground" : "bg-card text-foreground",
          )}
        >
          {message.content}
        </p>
        {onDelete && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label="메시지 옵션"
                disabled={disabled}
                className="text-muted-foreground"
              >
                <MoreHorizontal aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align={isUser ? "end" : "start"}>
              {canRegenerate && onRegenerate && (
                <DropdownMenuItem onSelect={onRegenerate}>
                  <RotateCw aria-hidden />
                  다시 생성
                </DropdownMenuItem>
              )}
              {isUser && onStartEdit && (
                <DropdownMenuItem onSelect={onStartEdit}>
                  <Pencil aria-hidden />
                  수정
                </DropdownMenuItem>
              )}
              <DropdownMenuItem variant="destructive" onSelect={onDelete}>
                <Trash2 aria-hidden />
                삭제
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
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
      <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-secondary px-3 py-1 text-xs font-medium text-secondary-foreground">
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
