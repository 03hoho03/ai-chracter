import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { characterImageArchiveKeys } from "@/entities/character-image-archive";
import {
  applyStreamEvent,
  buildEditPayload,
  buildRegeneratePayload,
  buildSendPayload,
  chatRoomKeys,
  truncateAndEdit,
} from "@/entities/chat-room";
import type { ChatMessage, ChatRoomState, ChatStreamEvent, ChatStreamRequest } from "@/entities/chat-room";
import { openChatStream } from "@/shared/lib/sse/openChatStream";

type PendingRequest = { payload: ChatStreamRequest; mode: "append" | "replaceLast" };
type SendMessageError = { retryPayload: PendingRequest };

/** techspec-chat-common.md §1 — 낙관적 업데이트가 핵심: 사용자 메시지는 스트림 성공 여부와
 * 무관하게 먼저 캐시에 반영해 실패해도 화면에서 사라지지 않는다(FR-88).
 * characterId는 캐릭터 챗일 때만(스토리 챗은 undefined) 전달 — 상황별 이미지가 트리거된
 * 메시지가 도착하면 이미지 보관함(US-074) 쿼리를 무효화한다(techspec-chat-character.md §1.2). */
export function useSendMessage(roomId: string, characterId?: string) {
  const queryClient = useQueryClient();
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<SendMessageError | null>(null);
  const [policyWarning, setPolicyWarning] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState("");

  async function openStream(pending: PendingRequest) {
    setIsSending(true);
    setError(null);
    setPolicyWarning(null);
    setStreamingText("");

    try {
      for await (const event of openChatStream<ChatStreamEvent>(pending.payload)) {
        if (event.type === "token") {
          setStreamingText((prev) => prev + event.delta);
        } else if (event.type === "policyWarning") {
          setPolicyWarning(event.message);
        } else if (event.type === "error") {
          setError({ retryPayload: pending });
        }
        applyStreamEvent(queryClient, roomId, event, {
          mode: pending.mode,
          onDone: (message) => {
            if (message.imageId && characterId) {
              queryClient.invalidateQueries({ queryKey: characterImageArchiveKeys.list(characterId) });
            }
          },
        });
      }
    } catch {
      setError({ retryPayload: pending });
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

    void openStream({ payload: buildSendPayload({ roomId, text, shortcutId }), mode: "append" });
  }

  // techspec-chat-common.md §2.1 — 마지막 AI 응답만 새 텍스트로 교체(같은 턴), 새 사용자
  // 메시지를 추가하지 않는다.
  function regenerate(): void {
    if (isSending) return;
    void openStream({ payload: buildRegeneratePayload({ roomId }), mode: "replaceLast" });
  }

  // truncateAndEdit로 그 메시지 이후를 먼저 잘라낸 뒤, 일반 전송과 동일한 스트리밍 흐름을
  // 재실행한다(편집 대상 이후 새 응답을 append) — send()와 달리 낙관적 사용자 메시지를 새로
  // 추가하지 않는다(이미 캐시에 있는 메시지를 truncateAndEdit이 갱신한다).
  function editMessage(messageId: string, text: string): void {
    if (isSending) return;
    truncateAndEdit(queryClient, roomId, messageId, text);
    void openStream({ payload: buildEditPayload({ roomId, messageId, text }), mode: "append" });
  }

  function retry(): void {
    if (!error) return;
    // 동일 payload로 스트림만 재오픈 — 사용자 메시지를 중복 추가하지 않음(send()를 다시 호출하지 않음).
    void openStream(error.retryPayload);
  }

  return { send, retry, regenerate, editMessage, isSending, error, policyWarning, streamingText };
}
