import { useEffect, useRef, useState } from "react";
import { Avatar, AvatarFallback, AvatarImage } from "@ai-character-chat/ui/components/avatar";
import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ArrowLeft, RotateCw, Send, TriangleAlert } from "lucide-react";

import { useChatRoomQuery } from "../../../entities/chat-room";
import { useContentDetailQuery } from "../../../entities/content";
import { useSendMessage } from "../../../features/send-message";
import { MessageBubble, TypingIndicator } from "./MessageBubble";

function ChatRoomSkeleton() {
  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="h-16 w-2/3 animate-pulse rounded-lg bg-muted" />
      <div className="ml-auto h-10 w-1/2 animate-pulse rounded-lg bg-muted" />
      <div className="h-12 w-3/5 animate-pulse rounded-lg bg-muted" />
    </div>
  );
}

// techspec-chat-character.md, techspec-chat-common.md §1/§5 — US-055: 대화방 상세 조회 + 메시지
// 전송/스트리밍 표시 + 오류·정책경고 배너를 갖춘 캐릭터 챗 대화 화면.
export function ChatRoomView({ roomId }: { roomId: string }) {
  const roomQuery = useChatRoomQuery(roomId);
  const room = roomQuery.data;
  const characterQuery = useContentDetailQuery(room?.contentId ?? "", room !== undefined);
  const character = characterQuery.data;

  const { send, retry, isSending, error, policyWarning, streamingText } = useSendMessage(roomId);
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [room?.messages.length, streamingText]);

  useEffect(() => {
    if (policyWarning) inputRef.current?.focus();
  }, [policyWarning]);

  function handleSend() {
    const trimmed = text.trim();
    if (!trimmed || isSending) return;
    send(trimmed);
    setText("");
  }

  if (roomQuery.isPending) {
    return (
      <div className="flex h-[calc(100dvh-3.5rem)] flex-col">
        <ChatRoomSkeleton />
      </div>
    );
  }

  if (roomQuery.isError || !room) {
    return (
      <div className="flex h-[calc(100dvh-3.5rem)] items-center justify-center px-6">
        <p className="text-sm text-destructive">대화방을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] flex-col">
      <header className="flex shrink-0 items-center gap-3 border-b border-border px-4 py-3">
        <Button variant="ghost" size="icon" aria-label="뒤로가기" onClick={() => window.history.back()}>
          <ArrowLeft aria-hidden className="size-4" />
        </Button>
        <Avatar>
          <AvatarImage src={character?.thumbnailUrl ?? undefined} alt="" />
          <AvatarFallback>{character?.name.slice(0, 1) ?? "?"}</AvatarFallback>
        </Avatar>
        <div className="flex min-w-0 flex-col">
          <span className="truncate text-sm font-semibold text-foreground">{character?.name ?? "캐릭터"}</span>
          <span className="truncate text-xs text-muted-foreground">{room.name}</span>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        <div className="flex flex-col gap-3">
          {room.messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}

          {isSending &&
            (streamingText ? (
              <MessageBubble message={{ id: "streaming", role: "assistant", content: streamingText, createdAt: "" }} />
            ) : (
              <TypingIndicator />
            ))}

          {error && (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-3.5 py-2.5">
              <span className="text-xs text-destructive">응답 생성에 실패했습니다 · 다시 시도</span>
              <Button variant="destructive" size="sm" onClick={retry}>
                <RotateCw aria-hidden className="size-3.5" />
                다시 시도
              </Button>
            </div>
          )}

          {policyWarning && (
            <div className="flex items-center gap-2 rounded-lg border border-border bg-secondary/50 px-3.5 py-2.5">
              <TriangleAlert aria-hidden className="size-4 shrink-0 text-[oklch(0.72_0.14_50)]" />
              <span className="text-xs text-muted-foreground">{policyWarning}</span>
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      <div className="shrink-0 border-t border-border bg-background p-3">
        <div className="flex items-end gap-2">
          <Textarea
            ref={inputRef}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                handleSend();
              }
            }}
            placeholder="메시지를 입력하세요"
            disabled={isSending}
            rows={1}
            className="max-h-40 resize-none"
          />
          <Button size="icon" aria-label="전송" disabled={isSending || !text.trim()} onClick={handleSend}>
            <Send aria-hidden className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
