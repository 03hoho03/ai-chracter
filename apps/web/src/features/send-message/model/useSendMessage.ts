import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { characterImageArchiveKeys } from "@/entities/character-image-archive";
import {
  applyStreamEvent,
  buildEditPayload,
  buildRegeneratePayload,
  buildSendPayload,
  chatRoomKeys,
  getChatRateLimit,
  truncateAndEdit,
} from "@/entities/chat-room";
import { chatStreamEventSchema } from "@/entities/chat-room";
import type { ChatMessage, ChatRateLimit, ChatRoomState, ChatStreamRequest } from "@/entities/chat-room";
import { cloverKeys } from "@/entities/clover";
import type { CloverSpendConfirmOutcome } from "@/entities/clover";
import { isLegalReconsentRequiredError } from "@/entities/legal";
import { sessionKeys } from "@/entities/session";
import { openChatStream } from "@/shared/api/sse/openChatStream";

type PendingRequest = { payload: ChatStreamRequest; mode: "append" | "replaceLast" };

// TS-04 — isSending(boolean) + error(SendMessageError | null)의 조합은 "전송 중이면서 동시에
// 에러"라는 불가능 상태를 타입으로 막지 못했다. 판별 유니언으로 상태를 하나로 묶는다.
// limit-goal-prompt.md RL-15 — 429는 안내 문구와 다음 행동이 다른 오류라(기다리면 풀린다) 배너가
// 분기할 수 있게 `rateLimit`을 함께 싣는다. 429가 아닌 실패는 값이 없고 기존 배너 그대로다.
// clover-goal-prompt.md CL-19 / S12 C-3 — `declined`는 **사용자가 확인 모달에서 그만둔 것**이라
// 실패가 아니다. 같은 `error` 자리를 쓰는 이유는 낙관적 사용자 메시지가 이미 목록에 있어
// 아무것도 안 보여 주면 멈춘 것처럼 읽히기 때문이고(재시도 버튼도 그대로 유용하다), 문구만
// 배너가 갈라 쓴다 — 실패하지 않은 일에 "실패했습니다"를 쓰면 거짓이다.
type SendMessageStatus =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "error"; retryPayload: PendingRequest; rateLimit?: ChatRateLimit; declined?: boolean };

/** techspec-chat-common.md §1 — 낙관적 업데이트가 핵심: 사용자 메시지는 스트림 성공 여부와
 * 무관하게 먼저 캐시에 반영해 실패해도 화면에서 사라지지 않는다(FR-88).
 * characterId는 캐릭터 챗일 때만(스토리 챗은 undefined) 전달 — 상황별 이미지가 트리거된
 * 메시지가 도착하면 이미지 보관함(US-074) 쿼리를 무효화한다(techspec-chat-character.md §1.2). */
export function useSendMessage(
  roomId: string,
  characterId?: string,
  /** clover-goal-prompt.md CL-19 — 오류를 받아 **"재시도해도 되는가"** 를 돌려준다.
   *
   * 🔴 위젯이 주입하는 이유는 FSD다 — 모달은 `features/confirm-clover-spend`에 있고 feature가
   * 다른 feature를 import하는 선례가 이 저장소에 **0건**이다(`.call()` 호출부는 전부
   * `widgets`/`pages`이거나 같은 슬라이스 안이다). 단가도 표면마다 달라 위젯이 **미리 묶어**
   * 넘긴다 — 그래서 이 훅은 클로버 단가를 알 필요가 없다.
   *
   * 안 넘기면 확인 429가 평소의 오류 배너로 떨어질 뿐 동작은 깨지지 않는다 — 다만 그 화면에서는
   * 클로버를 영영 못 쓴다. */
  confirmCloverSpend?: (error: unknown) => Promise<CloverSpendConfirmOutcome>,
) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<SendMessageStatus>({ kind: "idle" });
  const [policyWarning, setPolicyWarning] = useState<string>();
  const [streamingText, setStreamingText] = useState("");

  /** `allowCloverConfirm`은 **무한 루프 차단기**다(clover-goal-prompt.md CL-19). 동의 뒤 재시도는
   * `false`로 들어가므로, 재시도가 또 `CLOVER_CONFIRM_REQUIRED`를 받아도 모달을 다시 띄우지 않고
   * 평범한 오류로 끝난다.
   *
   * ⚠️ 이 차단기가 막는 것은 **"서버가 동의를 인정하지 않는 경우"** 하나뿐이다. 흔히 드는 두 사유는
   * 여기서 성립하지 않는다:
   * - *동의 POST 실패* — `useConfirmCloverSpend`가 그때 `false`를 돌려주므로 **재시도 자체가 없다**.
   * - *자정을 막 넘김* — 채팅 일일 키에는 KST 날짜가 섞여 있어(`core/rate_limit_gate.py`의
   *   `_DAY_SCOPE` 키 조립) 자정에 카운트가 0으로 리셋되고, 그러면 클로버 분기에 **도달조차
   *   하지 않아** 재전송이 무료로 통과한다. 이 사유가 참인 것은 시간당 충전이라 자정과 무관한
   *   **이미지 쪽**이다.
   *
   * 그래서 재시도는 **커밋된 동의** 뒤에만 일어나고 서버는 통과시켜야 정상이다. 차단기는 그
   * "정상"을 FE가 증명할 수 없다는 사실에 대한 보험이다 — 게이트 조건이 나중에 바뀌는 등으로
   * 둘의 판단이 갈리면, 없을 때 그 불일치가 **무한 왕복**이 된다. 사용자 조작 한 번당 모달을
   * 한 번으로 묶는 것이 이 인자의 전부다. */
  async function openStream(pending: PendingRequest, allowCloverConfirm = true) {
    setStatus({ kind: "sending" });
    setPolicyWarning(undefined);
    setStreamingText("");
    // finally에서 status를 읽으면 위 setStatus가 아직 반영되지 않은 클로저 값을 보므로, 이번 스트림에서
    // 에러가 났는지는 로컬 변수로 따로 추적한다.
    let hasErrored = false;

    try {
      for await (const event of openChatStream(pending.payload, chatStreamEventSchema)) {
        if (event.type === "token") {
          setStreamingText((prev) => prev + event.delta);
        } else if (event.type === "policyWarning") {
          setPolicyWarning(event.message);
        } else if (event.type === "error") {
          hasErrored = true;
          // 스트림 안에서 온 오류는 상한과 무관하다(게이트는 스트림이 열리기 전에 429로 막는다).
          setStatus({ kind: "error", retryPayload: pending });
        }
        applyStreamEvent(queryClient, roomId, event, {
          mode: pending.mode,
          onDone: (message) => {
            if (message.imageId && characterId) {
              void queryClient.invalidateQueries({ queryKey: characterImageArchiveKeys.list(characterId) });
            }
            // clover-techspec.md CT-12 — 무료 일일분을 넘긴 턴은 클로버를 깎았다(CL-1). 이 훅이
            // 전송·재생성·편집 셋을 모두 태우므로 세 표면의 차감이 여기 한 곳에서 반영된다.
            // `invalidateQueries`를 쓰는 이유: 잔액은 "낡았다"이지 "틀렸다"(버리는 값)가 아니다
            // (`apps/web/CLAUDE.md` §데이터/상태의 판단 기준).
            void queryClient.invalidateQueries({ queryKey: cloverKeys.balance() });
          },
        });
      }
    } catch (error) {
      hasErrored = true;
      // RL-17 — SSE는 뮤테이션이 아니라 `app/AppProviders.tsx`의 MutationCache.onError가 못 본다.
      // 재동의 403을 여기서 잡지 않으면 채팅 4경로에서만 모달이 뜨지 않는다(세션을 다시 조회하면
      // ReconsentModal이 `GET /me`의 플래그로 뜬다 — CG-12와 같은 처리다).
      if (isLegalReconsentRequiredError(error)) {
        void queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
      }
      // clover-goal-prompt.md CL-19 — 동의가 필요하면 배너가 아니라 모달이다. 동의하면 **같은
      // payload로** 재전송한다(`send()`를 다시 부르지 않으므로 낙관적 사용자 메시지가 중복되지
      // 않는다 — `retry()`와 같은 이유로 `openStream`을 직접 부른다).
      const confirmOutcome = allowCloverConfirm ? await confirmCloverSpend?.(error) : undefined;
      if (confirmOutcome === "retry") {
        await openStream(pending, false);
        return;
      }
      setStatus({
        kind: "error",
        retryPayload: pending,
        rateLimit: getChatRateLimit(error),
        // S12 C-3 — 그만두기는 실패가 아니다. 배너가 이 값으로 문구를 가른다.
        declined: confirmOutcome === "declined",
      });
    } finally {
      setStreamingText("");
      if (!hasErrored) setStatus({ kind: "idle" });
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
    if (status.kind === "sending") return;
    void openStream({ payload: buildRegeneratePayload({ roomId }), mode: "replaceLast" });
  }

  // truncateAndEdit로 그 메시지 이후를 먼저 잘라낸 뒤, 일반 전송과 동일한 스트리밍 흐름을
  // 재실행한다(편집 대상 이후 새 응답을 append) — send()와 달리 낙관적 사용자 메시지를 새로
  // 추가하지 않는다(이미 캐시에 있는 메시지를 truncateAndEdit이 갱신한다).
  function editMessage(messageId: string, text: string): void {
    if (status.kind === "sending") return;
    truncateAndEdit(queryClient, roomId, messageId, text);
    void openStream({ payload: buildEditPayload({ roomId, messageId, text }), mode: "append" });
  }

  function retry(): void {
    if (status.kind !== "error") return;
    // 동일 payload로 스트림만 재오픈 — 사용자 메시지를 중복 추가하지 않음(send()를 다시 호출하지 않음).
    void openStream(status.retryPayload);
  }

  return { send, retry, regenerate, editMessage, status, policyWarning, streamingText };
}
