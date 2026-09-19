import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { getChatRateLimit, type ChatRateLimit } from "@/entities/chat-room";
import { cloverKeys } from "@/entities/clover";
import type { CloverSpendConfirmOutcome } from "@/entities/clover";
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
// S12 C-3 — `declined`는 확인 모달에서 **사용자가 그만둔 것**이라 실패가 아니다. 문구만 배너가
// 갈라 쓴다(`useSendMessage`와 같은 처방).
type PreviewSendStatus =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "error"; rateLimit?: ChatRateLimit; declined?: boolean };

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
export function usePreviewSendMessage(
  /** clover-goal-prompt.md CL-19 — 오류를 받아 **"재시도해도 되는가"** 를 돌려준다.
   * `useSendMessage`와 같은 이유로 위젯이 주입한다(feature끼리 import하지 않는다, 선례 0건).
   * 미리보기도 채팅 4경로의 같은 게이트를 지나므로 같은 확인이 필요하다. */
  confirmCloverSpend?: (error: unknown) => Promise<CloverSpendConfirmOutcome>,
) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<PreviewSendStatus>({ kind: "idle" });
  const [policyWarning, setPolicyWarning] = useState<string>();
  const [streamingText, setStreamingText] = useState("");

  /** `allowCloverConfirm`은 **무한 루프 차단기**다 — 동의 뒤 재시도는 `false`로 들어가므로
   * 재시도가 또 확인 429를 받아도 모달을 다시 띄우지 않는다.
   *
   * 미리보기도 채팅 일일 창을 공유하므로 막는 대상이 `useSendMessage`와 같다 — **서버가 커밋된
   * 동의를 인정하지 않는 경우** 하나뿐이고, 동의 POST 실패나 자정 넘김은 여기서 성립하지 않는다.
   * 사유는 그쪽 주석에 적어 뒀다(사본을 두지 않는다). */
  async function send(
    previewSessionId: string,
    text: string,
    shortcutId?: string,
    allowCloverConfirm = true,
  ): Promise<void> {
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
    // 🔴 동의 뒤 재전송으로 넘어가면 **이 호출의 `finally`가 안쪽 호출의 상태를 덮어쓰면
    // 안 된다**(`return`은 `finally`를 건너뛰지 않는다). 안쪽이 이미 자기 상태를 세웠으므로
    // 여기서는 아무것도 하지 않는다.
    let handedOffToRetry = false;
    // S12 C-3 — 그만두기를 실패와 구분한다(`finally`가 상태를 세우므로 바깥에 둔다).
    let declined = false;

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
      // clover-goal-prompt.md CL-19 — 동의가 필요하면 배너가 아니라 모달이고, 동의하면 같은
      // 텍스트로 한 번 더 보낸다. 🔴 재전송은 `send`를 다시 부르므로 **낙관적 사용자 메시지가
      // 한 번 더 추가된다** — 그래서 아래 `finally`가 끝난 뒤가 아니라 여기서 `return`하지 않고,
      // 재전송 전에 방금 넣은 낙관적 메시지를 되돌린다.
      const confirmOutcome = allowCloverConfirm ? await confirmCloverSpend?.(error) : undefined;
      declined = confirmOutcome === "declined";
      if (confirmOutcome === "retry") {
        queryClient.setQueryData<PreviewSessionState>(
          previewSessionKeys.detail(previewSessionId),
          (prev) =>
            prev && { ...prev, messages: prev.messages.filter((m) => m.id !== optimisticMessage.id) },
        );
        setStreamingText("");
        handedOffToRetry = true;
        await send(previewSessionId, text, shortcutId, false);
        return;
      }
      rateLimit = getChatRateLimit(error);
    } finally {
      if (!handedOffToRetry) {
        setStreamingText("");
        setStatus(hasErrored ? { kind: "error", rateLimit, declined } : { kind: "idle" });
      }
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
