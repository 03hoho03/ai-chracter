import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { getChatRateLimit, type ChatRateLimit } from "@/entities/chat-room";
import { cloverKeys } from "@/entities/clover";
import { isLegalReconsentRequiredError } from "@/entities/legal";
import {
  applyPreviewStreamEvent,
  buildPreviewSendPayload,
  previewSessionKeys,
} from "@/entities/preview-session";
import { previewStreamEventSchema } from "@/entities/preview-session";
import type { PreviewChatMessage, PreviewSessionState } from "@/entities/preview-session";
import { sessionKeys } from "@/entities/session";
import { openChatStream } from "@/shared/api/sse/openChatStream";

// TS-04 — isSending(boolean) + error(boolean)의 조합은 "전송 중이면서 동시에 에러"라는 불가능 상태를
// 타입으로 막지 못했다(useSendMessage와 동일한 처방). 재시도가 없어 useSendMessage와 달리 retryPayload는
// 필요 없다. limit-goal-prompt.md RL-23 — 429만 배너 문구가 갈리므로 그 값만 함께 싣는다.
type PreviewSendStatus =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "error"; rateLimit?: ChatRateLimit };

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
    // setStatus가 finally의 단일 호출이므로(아래 V-5) 429 정보도 그때까지 로컬 변수로 들고 있는다.
    let rateLimit: ChatRateLimit | undefined;

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
    } catch (error) {
      hasErrored = true;
      // RL-17 — useSendMessage와 같은 이유로 여기서도 재동의 403을 잡는다(SSE는 MutationCache가 못 본다).
      if (isLegalReconsentRequiredError(error)) {
        void queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
      }
      rateLimit = getChatRateLimit(error);
    } finally {
      setStreamingText("");
      setStatus(hasErrored ? { kind: "error", rateLimit } : { kind: "idle" });
      // clover-techspec.md CT-12 — 미리보기도 채팅 4경로의 같은 게이트를 지나므로 무료 일일분을
      // 넘기면 클로버가 깎인다(RL-23 — 미리보기 문구가 "같은 한도를 쓴다"고 먼저 말하는 이유).
      //
      // `useSendMessage`와 달리 `onDone`을 쓰지 않는다 — `applyPreviewStreamEvent`에는 그 확장 훅이
      // 없고(`entities/preview-session`은 별도 쿼리 키만 건드린다), 여기에 훅을 새로 뚫는 것보다
      // 호출부에서 한 줄 부르는 쪽이 작다. `finally`인 것은 덤으로 정확하다: 차감된 뒤 실패한 턴도
      // (환불됐든 정책 위반으로 소모됐든) 잔액이 바뀌므로 성공 경로만 보면 놓친다.
      void queryClient.invalidateQueries({ queryKey: cloverKeys.balance() });
    }
  }

  return { send, status, policyWarning, streamingText };
}
