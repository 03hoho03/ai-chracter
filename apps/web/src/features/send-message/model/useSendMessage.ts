import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { applyStreamEvent, buildSendPayload, chatRoomKeys } from "../../../entities/chat-room";
import type { ChatMessage, ChatRoomState, ChatStreamEvent, SendMessageRequest } from "../../../entities/chat-room";
import { openChatStream } from "../../../shared/lib/sse/openChatStream";

type SendMessageError = { retryPayload: SendMessageRequest };

/** techspec-chat-common.md §1 — 낙관적 업데이트가 핵심: 사용자 메시지는 스트림 성공 여부와
 * 무관하게 먼저 캐시에 반영해 실패해도 화면에서 사라지지 않는다(FR-88). */
export function useSendMessage(roomId: string) {
  const queryClient = useQueryClient();
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<SendMessageError | null>(null);
  const [policyWarning, setPolicyWarning] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState("");

  async function openStream(payload: SendMessageRequest) {
    setIsSending(true);
    setError(null);
    setPolicyWarning(null);
    setStreamingText("");

    try {
      for await (const event of openChatStream<ChatStreamEvent>(payload)) {
        if (event.type === "token") {
          setStreamingText((prev) => prev + event.delta);
        } else if (event.type === "policyWarning") {
          setPolicyWarning(event.message);
        } else if (event.type === "error") {
          setError({ retryPayload: payload });
        }
        applyStreamEvent(queryClient, roomId, event);
      }
    } catch {
      setError({ retryPayload: payload });
    } finally {
      setStreamingText("");
      setIsSending(false);
    }
  }

  function send(text: string, shortcutId?: string): void {
    const optimisticMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      createdAt: new Date().toISOString(),
    };
    queryClient.setQueryData<ChatRoomState>(
      chatRoomKeys.detail(roomId),
      (prev) => prev && { ...prev, messages: [...prev.messages, optimisticMessage] },
    );

    void openStream(buildSendPayload({ roomId, text, shortcutId }));
  }

  function retry(): void {
    if (!error) return;
    // 동일 payload로 스트림만 재오픈 — 사용자 메시지를 중복 추가하지 않음(send()를 다시 호출하지 않음).
    void openStream(error.retryPayload);
  }

  return { send, retry, isSending, error, policyWarning, streamingText };
}
