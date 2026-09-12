import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  applyPreviewStreamEvent,
  buildPreviewSendPayload,
  previewSessionKeys,
} from "@/entities/preview-session";
import { previewStreamEventSchema } from "@/entities/preview-session";
import type { PreviewChatMessage, PreviewSessionState } from "@/entities/preview-session";
import { openChatStream } from "@/shared/api/sse/openChatStream";

// TS-04 — isSending(boolean) + error(boolean)의 조합은 "전송 중이면서 동시에 에러"라는 불가능 상태를
// 타입으로 막지 못했다(useSendMessage와 동일한 처방). 재시도가 없어 useSendMessage와 달리 retryPayload는
// 필요 없다.
type PreviewSendStatus = { kind: "idle" } | { kind: "sending" } | { kind: "error" };

/**
 * features/send-message의 useSendMessage(techspec-chat-common.md §1)와 동일한 낙관적 업데이트+SSE
 * 소비 모양이지만, 미리보기는 재생성/수정/삭제가 없어(BE도 POST .../messages 하나뿐, US-089) send만
 * 남긴 단순화된 버전이다.
 *
 * `previewSessionId`는 훅 파라미터가 아니라 `send()` 호출마다 받는다(D-7, builder-techspec.md §6-2) —
 * 지연 시작 때문에 세션이 "첫 전송 직전"에야 생기는데, 훅 레벨 파라미터로 고정하면 세션을 막 만든
 * 직후에도 그 렌더가 반영되기 전이라 여전히 `undefined`를 가리키는 stale 클로저를 잡게 된다.
 * `PreviewSessionView`가 세션을 보장한 뒤 받은 id를 이 인자로 직접 태운다.
 */
export function usePreviewSendMessage() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<PreviewSendStatus>({ kind: "idle" });
  const [policyWarning, setPolicyWarning] = useState<string>();
  const [streamingText, setStreamingText] = useState("");

  async function send(previewSessionId: string, text: string, shortcutId?: string): Promise<void> {
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

    setStatus({ kind: "sending" });
    setPolicyWarning(undefined);
    setStreamingText("");
    // finally에서 status를 읽으면 위 setStatus가 아직 반영되지 않은 클로저 값을 보므로, 이번 스트림에서
    // 에러가 났는지는 로컬 변수로 따로 추적한다(useSendMessage와 동일한 사유).
    let hasErrored = false;

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
          // V-5 — 여기서 즉시 setStatus({kind:"error"})를 부르지 않는다. isSending은 status.kind==="sending"의
          // 파생값이라, 그러면 실제 채팅방(useSendMessage)과 달리 스트림이 아직 열려 있는데 입력창이 풀린다.
          // BE apps/api/src/api/chat/router.py의 send_preview_message는 안쪽 제너레이터가 error로 return한
          // 뒤에도 바깥에서 update_preview_session(Redis SET)을 마쳐야 스트림이 닫히므로, 그 창에 재전송하면
          // _owned_preview_session_dependency의 락 없는 read-modify-write가 직전 메시지를 잃을 수 있다
          // (fe-convention-refactor-progress.md V-5). 그래서 이 훅만 확정을 finally로 미뤄 옛 main처럼
          // 스트림 종료까지 입력을 잠근다 — hasErrored만 세우고 setStatus는 finally의 단일 호출에 맡긴다.
          hasErrored = true;
        }
        applyPreviewStreamEvent(queryClient, previewSessionId, event);
      }
    } catch {
      hasErrored = true;
    } finally {
      setStreamingText("");
      setStatus(hasErrored ? { kind: "error" } : { kind: "idle" });
    }
  }

  return { send, status, policyWarning, streamingText };
}
