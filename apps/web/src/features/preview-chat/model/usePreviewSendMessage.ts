import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  applyPreviewStreamEvent,
  buildPreviewSendPayload,
  previewSessionKeys,
} from "@/entities/preview-session";
import { previewStreamEventSchema } from "@/entities/preview-session";
import type { PreviewChatMessage, PreviewSessionState } from "@/entities/preview-session";
import { openChatStream } from "@/shared/lib/sse/openChatStream";

/**
 * features/send-message의 useSendMessage(techspec-chat-common.md §1)와 동일한 낙관적 업데이트+SSE
 * 소비 모양이지만, 미리보기는 재생성/수정/삭제가 없어(BE도 POST .../messages 하나뿐, US-089) send만
 * 남긴 단순화된 버전이다.
 */
export function usePreviewSendMessage(previewSessionId: string | undefined) {
  const queryClient = useQueryClient();
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState(false);
  const [policyWarning, setPolicyWarning] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState("");

  async function send(text: string, shortcutId?: string): Promise<void> {
    if (!previewSessionId) return;

    const optimisticMessage: PreviewChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      createdAt: new Date().toISOString(),
    };
    queryClient.setQueryData<PreviewSessionState>(
      previewSessionKeys.detail(previewSessionId),
      (prev) => prev && { ...prev, messages: [...prev.messages, optimisticMessage] },
    );

    setIsSending(true);
    setError(false);
    setPolicyWarning(null);
    setStreamingText("");

    try {
      for await (const event of openChatStream(
        buildPreviewSendPayload({ previewSessionId, text, shortcutId }),
        previewStreamEventSchema,
      )) {
        if (event.type === "token") {
          setStreamingText((prev) => prev + event.delta);
        } else if (event.type === "policyWarning") {
          setPolicyWarning(event.message);
        } else if (event.type === "error") {
          setError(true);
        }
        applyPreviewStreamEvent(queryClient, previewSessionId, event);
      }
    } catch {
      setError(true);
    } finally {
      setStreamingText("");
      setIsSending(false);
    }
  }

  return { send, isSending, error, policyWarning, streamingText };
}
